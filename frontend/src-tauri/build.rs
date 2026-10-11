fn main() {
    for path in ["../../LICENSE", "../../THIRD_PARTY_NOTICES.md", "../package-lock.json", "Cargo.toml", "Cargo.lock",
        "../scripts/native-notices.mjs", "../scripts/license-supplements", "gen/license-notices.gz", "gen/license-notices.json"] {
        println!("cargo:rerun-if-changed={path}");
    }
    let status = std::process::Command::new("node")
        .args(["../scripts/native-notices.mjs", "--check"])
        .status().expect("Node.js is required to validate embedded licenses");
    assert!(status.success(), "Run npm run licenses before compiling the desktop application");
    tauri_build::build()
}
