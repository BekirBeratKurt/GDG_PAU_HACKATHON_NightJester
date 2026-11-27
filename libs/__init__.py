"""NightJester modülleri.

pygame ilk kez import edilmeden önce tanıtım satırı kapatılır. Bu paket alt modüllerden
önce yüklendiği için ayar burada yapılır. (MediaPipe'ın açılıştaki birkaç C++ log satırı
ortam değişkeniyle kapatılamıyor ve zararsız.)
"""

import os

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
