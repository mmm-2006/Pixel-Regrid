#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
use base64::{engine::general_purpose::STANDARD, Engine};
use image::{ImageEncoder, ImageReader, ExtendedColorType};
use serde::Serialize;
use std::{collections::HashSet, fs::{self, OpenOptions}, io::Write, path::{Path, PathBuf}, sync::{Mutex, Arc, atomic::{AtomicBool, Ordering}}};
use tauri::{Manager, State};
#[derive(Default)]
struct Files { registry: Mutex<HashSet<PathBuf>>, scan_cancel: Arc<AtomicBool> }
#[derive(Serialize)]
struct Entry { key: String, name: String, path: String }
fn supported(p: &Path) -> bool {
    p.extension().and_then(|s| s.to_str()).map(|s| matches!(s.to_lowercase().as_str(), "png" | "jpg" | "jpeg" | "bmp" | "webp" | "tif" | "tiff")).unwrap_or(false)
}
fn register(paths: Vec<String>, files: &Files) -> Result<Vec<Entry>, String> {
    let mut entries = Vec::new();
    let mut registry = files.registry.lock().map_err(|e| e.to_string())?;
    for value in paths {
        let path = fs::canonicalize(value).map_err(|e| e.to_string())?;
        if !path.is_file() || !supported(&path) { continue }
        registry.insert(path.clone());
        let key = path.to_string_lossy().to_string();
        entries.push(Entry { name: path.file_name().unwrap().to_string_lossy().to_string(), path: key.clone(), key });
    }
    Ok(entries)
}
#[tauri::command]
fn add_paths(paths: Vec<String>, files: State<Files>) -> Result<Vec<Entry>, String> { register(paths, &files) }
#[derive(Serialize)]
struct Scan { entries: Vec<Entry>, warnings: Vec<String> }
#[tauri::command]
async fn scan_folder(folder: String, output_dir: String, files: State<'_, Files>) -> Result<Scan, String> {
    let cancel = files.scan_cancel.clone(); cancel.store(false, Ordering::Relaxed);
    let scanned = tauri::async_runtime::spawn_blocking(move || {
        let mut stack = vec![PathBuf::from(folder)]; let mut paths = Vec::new(); let mut warnings = Vec::new();
        let excluded = fs::canonicalize(output_dir).ok();
        while let Some(dir) = stack.pop() {
            if cancel.load(Ordering::Relaxed) { break }
            let entries = match fs::read_dir(&dir) { Ok(v) => v, Err(e) => { warnings.push(format!("{}：{}", dir.display(), e)); continue } };
            for entry in entries {
                if cancel.load(Ordering::Relaxed) { break }
                let entry = match entry { Ok(v) => v, Err(e) => { warnings.push(e.to_string()); continue } };
                let kind = match entry.file_type() { Ok(v) => v, Err(_) => continue }; let p = entry.path();
                if kind.is_symlink() { continue }
                if kind.is_dir() {
                    if entry.file_name().to_string_lossy().eq_ignore_ascii_case("perfect_pixel_output") || excluded.as_ref().is_some_and(|e| fs::canonicalize(&p).ok().as_ref() == Some(e)) { continue }
                    stack.push(p);
                } else if kind.is_file() && supported(&p) { paths.push(p.to_string_lossy().to_string()) }
            }
        }
        paths.sort(); (paths, warnings)
    }).await.map_err(|e| e.to_string())?;
    Ok(Scan { entries: register(scanned.0, &files)?, warnings: scanned.1 })
}
#[tauri::command]
fn cancel_scan(files: State<Files>) { files.scan_cancel.store(true, Ordering::Relaxed) }
fn imported(key: &str, files: &Files) -> Result<PathBuf, String> {
    let p = PathBuf::from(key);
    if !files.registry.lock().map_err(|e| e.to_string())?.contains(&p) { return Err("请先导入图片".into()) }
    Ok(p)
}
fn decode(path: &Path) -> Result<image::DynamicImage, String> {
    if fs::metadata(path).map_err(|e| e.to_string())?.len() > 128 * 1024 * 1024 { return Err("图片文件超过 128 MB".into()) }
    let mut reader = ImageReader::open(path).map_err(|e| e.to_string())?.with_guessed_format().map_err(|e| e.to_string())?;
    let mut limits = image::Limits::default(); limits.max_alloc = Some(256 * 1024 * 1024); reader.limits(limits);
    let decoded = reader.decode().map_err(|e| format!("图片读取失败：{e}"))?;
    if decoded.width() as u64 * decoded.height() as u64 > 32_000_000 { return Err("图片总像素不能超过 3200 万".into()) }
    Ok(decoded)
}
fn png(data: &[u8], width: u32, height: u32) -> Result<Vec<u8>, String> {
    if width == 0 || height == 0 || width as u64 * height as u64 > 32_000_000 || data.len() != width as usize * height as usize * 4 { return Err("图片尺寸或像素数据有误".into()) }
    let mut bytes = Vec::new();
    image::codecs::png::PngEncoder::new(&mut bytes).write_image(data, width, height, ExtendedColorType::Rgba8).map_err(|e| e.to_string())?;
    Ok(bytes)
}
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Pixels { width: u32, height: u32, has_alpha: bool, data: String }
#[tauri::command]
async fn read_image(key: String, files: State<'_, Files>) -> Result<Pixels, String> {
    let path = imported(&key, &files)?;
    tauri::async_runtime::spawn_blocking(move || {
        let image = decode(&path)?;
        Ok(Pixels { width: image.width(), height: image.height(), has_alpha: image.color().has_alpha(), data: STANDARD.encode(image.to_rgba8().as_raw()) })
    }).await.map_err(|e| e.to_string())?
}
#[tauri::command]
async fn encode_preview(data: String, width: u32, height: u32) -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let data = STANDARD.decode(data).map_err(|e| e.to_string())?;
        Ok(format!("data:image/png;base64,{}", STANDARD.encode(png(&data, width, height)?)))
    }).await.map_err(|e| e.to_string())?
}
#[tauri::command]
async fn save_image(key: String, data: String, width: u32, height: u32, output_dir: String, files: State<'_, Files>) -> Result<String, String> {
    let source = imported(&key, &files)?;
    tauri::async_runtime::spawn_blocking(move || {
        let folder = if output_dir.is_empty() { source.parent().unwrap().join("perfect_pixel_output") } else { PathBuf::from(output_dir) };
        let bytes = png(&STANDARD.decode(data).map_err(|e| e.to_string())?, width, height)?;
        write_output(&folder, &source.file_stem().unwrap().to_string_lossy(), &bytes, width, height)
    }).await.map_err(|e| e.to_string())?
}
fn write_output(folder: &Path, stem: &str, bytes: &[u8], width: u32, height: u32) -> Result<String, String> {
        fs::create_dir_all(folder).map_err(|e| e.to_string())?;
        for index in 1..100_000 {
            let suffix = if index == 1 { String::new() } else { format!("_{index}") };
            let dest = folder.join(format!("{stem}_perfect_{width}x{height}{suffix}.png"));
            match OpenOptions::new().write(true).create_new(true).open(&dest) {
                Ok(mut file) => {
                    if let Err(e) = file.write_all(bytes).and_then(|_| file.sync_all()) { drop(file); let _ = fs::remove_file(&dest); return Err(e.to_string()) }
                    return Ok(dest.to_string_lossy().to_string())
                }
                Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => continue,
                Err(e) => return Err(e.to_string()),
            }
        }
        Err("输出重名文件过多".into())
}
#[tauri::command]
fn open_output(path: String) -> Result<(), String> {
    let p = PathBuf::from(path); let folder = if p.is_dir() { p } else { p.parent().ok_or("输出路径有误")?.to_path_buf() };
    if !folder.is_dir() { return Err("输出目录不存在".into()) }
    std::process::Command::new("explorer.exe").arg(folder).spawn().map_err(|e| e.to_string())?;
    Ok(())
}
#[tauri::command]
fn load_settings(app: tauri::AppHandle) -> Result<serde_json::Value, String> {
    let file = app.path().app_data_dir().map_err(|e| e.to_string())?.join("settings.json");
    Ok(fs::read(file).ok().and_then(|s| serde_json::from_slice(&s).ok()).unwrap_or(serde_json::json!({})))
}
#[tauri::command]
fn store_settings(app: tauri::AppHandle, settings: serde_json::Value) -> Result<(), String> {
    let folder = app.path().app_data_dir().map_err(|e| e.to_string())?; fs::create_dir_all(&folder).map_err(|e| e.to_string())?;
    let temp = folder.join("settings.tmp"); let dest = folder.join("settings.json");
    fs::write(&temp, serde_json::to_vec_pretty(&settings).map_err(|e| e.to_string())?).map_err(|e| e.to_string())?;
    fs::rename(temp, dest).map_err(|e| e.to_string())
}
fn main() {
    tauri::Builder::default().manage(Files::default()).plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![add_paths, scan_folder, cancel_scan, read_image, encode_preview, save_image, open_output, load_settings, store_settings])
        .run(tauri::generate_context!()).expect("Perfect Pixel JS startup failed");
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rgba_png_roundtrip_preserves_semitransparent_and_hidden_rgb() {
        let raw = [23, 79, 141, 1, 71, 11, 201, 0, 255, 0, 0, 128];
        let encoded = png(&raw, 3, 1).unwrap();
        let decoded = image::load_from_memory(&encoded).unwrap().to_rgba8();
        assert_eq!(decoded.as_raw(), &raw);
        assert!(png(&raw, 4, 1).is_err());
    }
    #[test]
    fn unimported_read_is_rejected() { assert!(imported("unknown.png", &Files::default()).is_err()); }
    #[test]
    fn output_collisions_do_not_overwrite_source_or_existing_results() {
        let folder = std::env::temp_dir().join(format!("perfect-pixel-js-test-{}-{}", std::process::id(), std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos()));
        fs::create_dir(&folder).unwrap();
        let source = folder.join("原图.png"); fs::write(&source, b"original").unwrap();
        let first = write_output(&folder, "原图", b"first", 16, 16).unwrap();
        let second = write_output(&folder, "原图", b"second", 16, 16).unwrap();
        assert_ne!(first, second); assert_eq!(fs::read(&source).unwrap(), b"original");
        assert_eq!(fs::read(&first).unwrap(), b"first"); assert_eq!(fs::read(&second).unwrap(), b"second");
        fs::remove_file(source).unwrap(); fs::remove_file(first).unwrap(); fs::remove_file(second).unwrap(); fs::remove_dir(folder).unwrap();
    }
}
