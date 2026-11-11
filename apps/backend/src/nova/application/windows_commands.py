"""Deterministik metadata → yeni typed action. Sınıflandırma izin değildir."""
from nova.application.text_processing import TextProcessingService
from nova.domain.text import matching_text
from nova.domain.tasks import (ActionRequest,RegisteredAppArguments,ScopedSearchArguments,WebSearchArguments,TaskError)


def command_action(text: str,task_id: str,action_id: str,roots: tuple[str,...]) -> ActionRequest:
    result=TextProcessingService().process(text)
    if result.action is None:
        raise TaskError('COMMAND_UNSUPPORTED','Bu metin açık ve desteklenen bir Windows komutu değil.',422)
    target=result.action.target
    if result.action.operation=='open_application':
        if matching_text(target) not in ('not defteri','notepad'):
            raise TaskError('APP_NOT_ALLOWED','Bu uygulama izinli kayıtlı uygulamalar arasında değil.',403)
        return ActionRequest(task_id,action_id,'windows.open_app',RegisteredAppArguments('windows.notepad'),'windows.apps')
    if result.action.operation=='search_files':
        if len(roots)!=1:
            raise TaskError('ROOT_SELECTION_REQUIRED','Metinle arama için tam bir izinli kök yapılandırılmalı; kök yoksa erişim kapalıdır.',403)
        return ActionRequest(task_id,action_id,'windows.search_files',ScopedSearchArguments(roots[0],target),'windows.files')
    if result.action.operation=='web_search':
        return ActionRequest(task_id,action_id,'windows.web_search',WebSearchArguments(target),'windows.web')
    raise TaskError('COMMAND_UNSUPPORTED','Bu komut desteklenmiyor.',422)
