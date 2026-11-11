import re
import unicodedata
from urllib.parse import urlencode

from nova.domain.tasks import TaskError


def search_url(query: str) -> str:
    if (type(query) is not str or not 1<=len(query)<=256 or not query.strip()
        or any(unicodedata.category(c) in ('Cc','Cf','Cs') for c in query)
        or re.search(r'[a-zA-Z][a-zA-Z0-9+.-]*\s*:',query) or '://' in query or '\\' in query):
        raise TaskError('WEB_QUERY_INVALID','Yalnızca normal arama metni kabul edilir; URL veya protokol kullanmayın.',422)
    return 'https://www.google.com/search?'+urlencode({'q':query.strip()})
