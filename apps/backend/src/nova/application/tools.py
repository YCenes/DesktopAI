"""Sabit fake kayıtları; plugin discovery ve gerçek OS adapter'ı yoktur."""
from dataclasses import asdict
from nova.domain.tasks import (
    ActionRequest, OpenAppArguments, SearchFilesArguments, ToolDefinition,
    PermissionDecision, TaskError, ExecutionResult, identifier, RegisteredAppArguments, ScopedSearchArguments, OpenFileArguments, WebSearchArguments,
)
import re
from nova.domain.web_search import search_url


class ToolRegistry:
    def __init__(self, windows=None):
        self.windows = windows
        self._tools = {
            "fake.open_app": ToolDefinition("fake.open_app", ("app_id",), ("simulation.apps",),
                "simulated_launch", "high", "Yalnızca sahte uygulama açılış sonucu oluşturulur; Windows kontrol edilmez."),
            "fake.search_files": ToolDefinition("fake.search_files", ("query", "root_id"), ("simulation.files",),
                "synthetic_read", "low", "Yalnızca sabit sentetik dosya adları döner; diskte arama yapılmaz."),
        }
        if windows is not None:
            self._tools['windows.open_app']=ToolDefinition('windows.open_app',('app_id',),('windows.apps',),
                'process_launch','high','İzinli Not Defteri başlatılır. Pencerenin hazır olduğu doğrulanmaz.',False)
            self._tools['windows.search_files']=ToolDefinition('windows.search_files',('root_id','query'),('windows.files',),
                'metadata_read','low','Yalnızca açıkça izinli kökte sınırlı dosya metadata araması yapılır.',False)
            self._tools['windows.open_file']=ToolDefinition('windows.open_file',('root_id','relative_path','identity'),('windows.files',),
                'viewer_launch','high','Seçilen .txt dosyası kimliği yeniden doğrulanarak izinli Not Defteri ile açılmak üzere iletilir.',False)
            self._tools['windows.web_search']=ToolDefinition('windows.web_search',('query',),('windows.web',),
                'external_search','high','Arama terimleri Google hizmetine varsayılan tarayıcı üzerinden gönderilir. Sayfa içeriği okunmaz.',False)

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
        valid = valid or (action.tool_id=='windows.open_app' and type(args) is RegisteredAppArguments and args.app_id=='windows.notepad')
        valid = valid or (action.tool_id=='windows.search_files' and type(args) is ScopedSearchArguments and
            bool(re.fullmatch('[a-z][a-z0-9_-]{0,31}',args.root_id)) and 1<=len(args.query)<=64 and all(c.isalnum() or c in ' ._-' for c in args.query) and bool(args.query.strip()))
        valid = valid or (action.tool_id=='windows.open_file' and type(args) is OpenFileArguments and
            bool(re.fullmatch('[a-z][a-z0-9_-]{0,31}',args.root_id)) and 1<=len(args.relative_path)<=180 and bool(re.fullmatch('[a-f0-9]{64}',args.identity)))
        if action.tool_id=='windows.web_search' and type(args) is WebSearchArguments:
            search_url(args.query);valid=True
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
        model = {'fake.open_app':OpenAppArguments,'fake.search_files':SearchFilesArguments,'windows.open_app':RegisteredAppArguments,
            'windows.search_files':ScopedSearchArguments,'windows.open_file':OpenFileArguments,'windows.web_search':WebSearchArguments}[tool.tool_id]
        action = ActionRequest(data["task_id"], data["action_id"], data["tool_id"], model(**args), data["scope"])
        self.validate(action)
        return action

    def simulate(self, action: ActionRequest) -> ExecutionResult:
        # Yalnızca ExecutionService bu adapter girişini çağırır.
        self.validate(action)
        if not action.tool_id.startswith('fake.'):
            raise TaskError('SIMULATION_ONLY','Gerçek araç simülasyon kanalından çağrılamaz.')
        if isinstance(action.arguments, OpenAppArguments):
            return ExecutionResult("succeeded", f"Simülasyon: {action.arguments.app_id} açılmış kabul edildi. Windows'ta işlem yapılmadı.")
        return ExecutionResult("succeeded", "Simülasyon: ornek-rapor.txt bulundu. Gerçek dosyalara erişilmedi.")

    def execute(self, action: ActionRequest, deadline: float) -> ExecutionResult:
        self.validate(action)
        if action.tool_id.startswith('fake.'):
            return self.simulate(action)
        return self.windows.execute(action,deadline)


class PermissionService:
    def __init__(self, registry: ToolRegistry, version: str = "fake-policy-1"):
        self.registry, self.version = registry, (registry.windows.policy_version if registry.windows else version)

    def evaluate(self, action: ActionRequest) -> PermissionDecision:
        try:
            tool = self.registry.validate(action)
        except TaskError:
            return PermissionDecision("deny", "Araç, argüman veya kapsam desteklenmiyor.", self.version, "high")
        if tool.risk not in ("low", "high"):
            return PermissionDecision("deny", "Tanımlanmayan risk için izin verilmez.", self.version, "high")
        if not tool.simulated:
            try:
                if self.registry.windows is None:
                    raise TaskError('PERMISSION_DENIED','Windows araçları kapalı.')
                self.registry.windows.authorize(action)
            except (TaskError,OSError):
                return PermissionDecision('deny','Uygulama kimliği veya kapsam yetkili değil.',self.version,'high')
        decision = "require_approval" if tool.risk == "high" else "allow"
        return PermissionDecision(decision, "Yüksek risk için ekran onayı gerekli." if tool.risk == "high" else "İzinli kapsamda sınırlı salt-okuma yetkili.", self.version, tool.risk)
