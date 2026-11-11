fn main() {
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "backend_status",
            "backend_restart",
            "process_text",
            "create_simulated_task",
            "list_simulated_tasks",
            "get_simulated_task",
            "decide_simulated_approval",
            "cancel_simulated_task",
            "reconcile_simulated_task",
        ]),
    ))
    .expect("Tauri yapılandırması oluşturulamadı");
}
