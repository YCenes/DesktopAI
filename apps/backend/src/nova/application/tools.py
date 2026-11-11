"""Sabit fake kayıtları; plugin discovery ve gerçek OS adapter'ı yoktur."""
from dataclasses import asdict
from nova.domain.tasks import (
    ActionRequest, OpenAppArguments, SearchFilesArguments, ToolDefinition,
    PermissionDecision, TaskError, ExecutionResult, identifier,
)


class ToolRegistry:
    def __init__(self):
        self._tools = {
            "fake.open_app": ToolDefinition("fake.open_app", ("app_id",), ("simulation.apps",),
                "simulated_launch", "high", "Yalnızca sahte uygulama açılış sonucu oluşturulur; Windows kontrol edilmez."),
            "fake.search_files": ToolDefinition("fake.search_files", ("query", "root_id"), ("simulation.files",),
                "synthetic_read", "low", "Yalnızca sabit sentetik dosya adları döner; diskte arama yapılmaz."),
        }

    def resolve(self, tool_id: str) -> ToolDefinition:
        if tool_id not in self._tools:
            raise TaskError("TOOL_UNKNOWN", "Araç kayıtlı değil; işlem reddedildi.", 422)
        return self._tools[tool_id]

    def validate(self, action: ActionRequest) -> ToolDefinition:
        identifier(action.task_id); identifier(action.action_id)
        tool = self.resolve(action.tool_id)
        args = action.arguments
        valid = (
            action.tool_id == "fake.open_app" and type(args) is OpenAppArguments and args.app_id in ("demo.editor", "demo.admin")
        ) or (
            action.tool_id == "fake.search_files" and type(args) is SearchFilesArguments
            and args.query in ("ornek", "rapor") and args.root_id == "synthetic.documents"
        )
        if not valid:
            raise TaskError("ARGUMENTS_INVALID", "Araç argümanları desteklenmiyor.", 422)
        if action.scope not in tool.allowed_scopes:
            raise TaskError("SCOPE_DENIED", "İstenen kapsam bu araç için yetkili değil.", 403)
        return tool

    def from_dict(self, data: dict) -> ActionRequest:
        if set(data) != {"task_id", "action_id", "tool_id", "arguments", "scope"}:
            raise TaskError("INVALID_ACTION", "Eylem biçimi geçersiz.", 422)
        tool = self.resolve(data["tool_id"])
        args = data["arguments"]
        if type(args) is not dict or set(args) != set(tool.argument_schema):
            raise TaskError("ARGUMENTS_INVALID", "Araç argümanları geçersiz.", 422)
        model = OpenAppArguments if tool.tool_id == "fake.open_app" else SearchFilesArguments
        action = ActionRequest(data["task_id"], data["action_id"], data["tool_id"], model(**args), data["scope"])
        self.validate(action)
        return action

    def simulate(self, action: ActionRequest) -> ExecutionResult:
        # Yalnızca ExecutionService bu adapter girişini çağırır.
        self.validate(action)
        if isinstance(action.arguments, OpenAppArguments):
            return ExecutionResult("succeeded", f"Simülasyon: {action.arguments.app_id} açılmış kabul edildi. Windows'ta işlem yapılmadı.")
        return ExecutionResult("succeeded", "Simülasyon: ornek-rapor.txt bulundu. Gerçek dosyalara erişilmedi.")


class PermissionService:
    def __init__(self, registry: ToolRegistry, version: str = "fake-policy-1"):
        self.registry, self.version = registry, version

    def evaluate(self, action: ActionRequest) -> PermissionDecision:
        try:
            tool = self.registry.validate(action)
        except TaskError:
            return PermissionDecision("deny", "Araç, argüman veya kapsam desteklenmiyor.", self.version, "high")
        if tool.simulated is not True or tool.risk not in ("low", "high"):
            return PermissionDecision("deny", "Bu aşama yalnızca simülasyona izin verir.", self.version, "high")
        decision = "require_approval" if tool.risk == "high" else "allow"
        return PermissionDecision(decision, "Yüksek risk için ekran onayı gerekli." if tool.risk == "high" else "Sentetik salt-okuma yetkili.", self.version, tool.risk)
