# PLAN.md: NightJester

> **Bu dosya kimin için:** VS Code'da bu projede kod yazacak yapay zeka asistanı (Copilot / Claude vb.) ve ben.
> Bu dosya projenin **tek doğru kaynağıdır**. Kod, bu dosyadaki mimariye ve kod biçimine uymak zorundadır.
> Bir kural uymuyorsa ya da plan dışı bir karar gerekiyorsa, uygulamadan önce **bana sor**.

**Hackathon teması:** Yazılımcının hayatını kolaylaştırmak
**Süre:** Geliştirme için 5–5,5 saat (+ ~30 dk sunum hazırlığı)
**Durum:** Taslak v3 (fazlar, faz test listeleri, git kuralı). Revize edilecek.

---

## İçindekiler

0. [AI Asistan İçin Çalışma Kuralları](#0-ai-asistan-için-çalışma-kuralları)
1. [Proje Özeti](#1-proje-özeti)
2. [Tech Stack](#2-tech-stack)
3. [Kurulum (Hackathon Öncesi)](#3-kurulum-hackathon-öncesi)
4. [Mimari](#4-mimari)
5. [Tespit Algoritması](#5-tespit-algoritması)
6. [Hata Bitmask Tablosu](#6-hata-bitmask-tablosu)
7. [Kod Biçimi](#7-kod-biçimi)
8. [Geliştirme Planı (5–5,5 saat)](#8-geliştirme-planı-555-saat)
9. [Doğrulama ve Demo Senaryosu](#9-doğrulama-ve-demo-senaryosu)
10. [Varsayımlar ve Açık Konular](#10-varsayımlar-ve-açık-konular)

---

## 0. AI Asistan İçin Çalışma Kuralları

1. **Önce plan:** Bu dosya onaylanmadan kod yazılmaz. Ben açıkça **"başlayabilirsin"** demeden kod yazma.
2. **Faz faz ilerle:** [Bölüm 8](#8-geliştirme-planı-555-saat)'deki fazları (`Faz_1` … `Faz_9`) sırayla uygula. Bir fazın kapsamı dışına çıkma, sonraki fazın işini önden yapma.
   - Her fazın sonunda **dur** ve [Bölüm 8.2](#82-faz-sonu-raporu-şablonu)'deki **Faz Sonu Raporu**'nu yaz. Raporda o fazın test listesini ([Bölüm 8.3](#83-faz-test-listeleri)) bana adım adım ver: ne çalıştırılacak, ne yapılacak, ne görülmeli.
   - Testleri **ben** yaparım. Ben açıkça **"Faz_x onaylandı"** demeden bir sonraki faza geçme.
   - Bir test başarısız olduğunu söylersem sadece o fazın kapsamında düzelt ve aynı test listesini tekrar ver.
3. **Ayar kuralı (menuconfig kuralının karşılığı):**
   - `config/user_config.json` **benim** ayar dosyamdır. Bu dosyayı sen düzenleme. Bir değerin değişmesi gerekiyorsa hangi anahtarı neye ayarlamam gerektiğini söyle.
   - `config/default_config.json` şema ve varsayılan değer dosyasıdır (`Kconfig.projbuild` karşılığı). Yeni bir ayar eklerken buraya ekleyebilirsin.
   - VS Code / işletim sistemi ayarları (ör. kamera izni, `files.autoSave`) için de aynısı geçerli: sen yapma, bana hangi menüden neyi ayarlamam gerektiğini söyle.
4. **`restrictions.md`** dosyası varsa her zaman bu dosyanın önüne geçer.
5. **Karar benimse varsayım yapıp geçme.** Sor ya da varsayımı açıkça [Bölüm 10](#10-varsayımlar-ve-açık-konular)'a "varsayım" olarak ekle.
6. **Güncel API'ler:** MediaPipe için **Tasks API** (`mediapipe.tasks.python.vision.FaceLandmarker`) kullanılır. Legacy `mp.solutions.face_mesh` **kullanılmaz** (Google bu legacy çözümlerin desteğini sonlandırdı).
7. **Bağımlılık kuralı:** `requirements.txt` dışında paket ekleme. Yeni bir paket gerekiyorsa önce bana neden gerektiğini söyle.
8. **Git kuralı:** Git işlemlerini **ben** yaparım. `git add`, `commit`, `push`, `branch`, `checkout`, `tag`, `stash`, `reset` gibi komutları **çalıştırma** ve bana commit mesajı dayatma. (Kod Koruyucu modülünün uygulama içinde çalıştırdığı git komutları bu kuralın dışındadır. Onlar [Bölüm 4.9](#49-modül-sorumlulukları)'da tanımlıdır.)
9. **Demo önceliği:** Bir özellik zaman planını aşıyorsa onu yarım bırakıp çalışan sürümü bozma. [Bölüm 8.5](#85-kesme-listesi)'teki kesme listesine göre hareket et ve bana haber ver.

---

## 1. Proje Özeti

Bilgisayar kamerasını kullanarak yazılımcının uykusunun gelip gelmediğini **tamamen lokalde** tespit eden, arka planda (system tray) çalışan bir masaüstü uygulaması.

| Mod | Uyku tespit edildiğinde |
|---|---|
| **Normal mod** | Nazik bir masaüstü bildirimi: mola / uyku hatırlatıcısı. Bekleme süresi (cooldown) ile tekrar eder. |
| **Deadline modu** | Kullanıcının önceden seçtiği **ses dosyası, video linki veya lokal video** oynatılır. Kullanıcı uyandığı tespit edilene kadar ya da "Uyandım" butonuna basana kadar devam eder. Ayrıca **Kod Koruyucu** devreye girer ve çalışma alanını bozmadan git snapshot alır. |

**Fark yaratan özellikler (sunumda vurgulanacak):**
- **Kod Koruyucu:** Uyku anında `git stash create` + `git stash store` ile çalışma alanına **dokunmadan** değişikliklerin yedeği alınır.
- **Kişiye özel kalibrasyon:** Açılışta 5 saniyelik göz açıklık ölçümü.
- **Gizlilik:** Görüntü hiçbir yere gönderilmez ve kaydedilmez.
- **Yorgunluk raporu:** Oturum boyunca uyku olaylarının saatlere göre dağılımı.

---

## 2. Tech Stack

| Katman | Teknoloji | Neden |
|---|---|---|
| Dil | **Python 3.12** | MediaPipe ve diğer paketlerle en güvenli sürüm |
| Kamera | **OpenCV** (`cv2.VideoCapture`) | Kamera erişimi, frame işleme, overlay çizimi |
| Yüz noktaları | **MediaPipe Tasks: FaceLandmarker** | 478 yüz noktası + blendshape'ler (`eyeBlinkLeft`, `jawOpen` vb.), CPU'da gerçek zamanlı |
| Sayısal hesap | **NumPy** | EAR/MAR hesapları, kayan pencere |
| Arayüz | **CustomTkinter** + **Pillow** | Hızlı ve modern görünümlü panel; kamera önizlemesi `ImageTk` ile gösterilir |
| Arka plan / tray | **pystray** | System tray ikonu, mod değiştirme menüsü |
| Ses | **pygame** (`pygame.mixer`) | Alarm sesini döngüde çalma, ses seviyesini artırma |
| Video / link | `webbrowser` (stdlib), `os.startfile` / `subprocess` | Video linkini veya lokal videoyu varsayılan uygulamada açma |
| Bildirim | **plyer** | Çapraz platform masaüstü bildirimi |
| Git entegrasyonu | `subprocess` + **Git CLI** | Kod Koruyucu snapshot'ı |
| Kayıt / rapor | `sqlite3` (stdlib) | Oturum olaylarını saklama, saatlik rapor |
| Ayarlar | JSON + `dataclasses` (stdlib) | `default_config.json` + `user_config.json` birleştirme |
| Eşzamanlılık | `threading` (stdlib) | Her modül ayrı thread (ESP'deki task karşılığı) |
| Log | `logging` (stdlib) | Modül başına `TAG` |
| Kalite (dev) | **Ruff** (lint + format), **pytest** | Tek araçla stil kontrolü, algoritma birim testleri |

> **OpenCV notu:** `mediapipe` kurulurken bağımlılık olarak OpenCV'yi de çekebilir. Aynı ortamda hem `opencv-python` hem `opencv-contrib-python` kurulu olursa `cv2` import'u bozulabilir. Kurulumdan sonra `pip list | findstr opencv` (Windows) ile kontrol et. Birden fazla OpenCV paketi görünürse yalnızca birini bırak. **Uygulandı:** mediapipe `opencv-contrib-python`'a bağımlı olduğu için yalnızca o tutuldu, `opencv-python` listeden çıkarıldı.

### requirements.txt

```text
mediapipe
opencv-contrib-python
numpy
customtkinter
pillow
pystray
pygame
plyer
```

### requirements-dev.txt

```text
ruff
pytest
```

> Kurulum çalıştıktan sonra `pip freeze > requirements.lock.txt` ile sürümler sabitlenir. Hackathon sırasında paket güncellenmez.

---

## 3. Kurulum (Hackathon Öncesi)

**Bu bölüm hackathon başlamadan yapılmalı.** 5,5 saatlik plana dahil değildir.

### 3.1 Bilgisayara kurulacak uygulamalar (VS Code, Python ve OpenCV dışında)

| Uygulama | Neden | Not |
|---|---|---|
| **Git** | Kod Koruyucu modülü Git CLI'ı çağırır, ayrıca projenin kendi versiyon kontrolü için | Windows: "Git for Windows". Kurulumdan sonra `git --version` çalışmalı. |
| **VS Code eklentileri** | | |
| ↳ Python (Microsoft) | Çalıştırma, debug, venv seçimi | Python Debugger eklentisi bununla birlikte gelir |
| ↳ Pylance | Tip kontrolü, otomatik tamamlama | |
| ↳ Ruff (Astral) | Kaydederken lint + format | |
| ↳ (opsiyonel) Markdown Preview | PLAN.md / README okumak için | VS Code'da yerleşik önizleme de var |

Ek bir medya oynatıcıya gerek yok: ses `pygame` ile, video linkleri varsayılan tarayıcıyla, lokal videolar varsayılan oynatıcıyla açılır.

### 3.2 Proje ortamı

```powershell
# Proje klasöründe
py -3.12 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt -r requirements-dev.txt
```

VS Code'da: `Ctrl+Shift+P` → **Python: Select Interpreter** → `.venv`

### 3.3 Model dosyası

FaceLandmarker için bir `.task` model dosyası gerekir. MediaPipe Face Landmarker dokümantasyonundaki **Models** bölümünden `face_landmarker.task` dosyasını indir ve şuraya koy:

```
assets/models/face_landmarker.task
```

### 3.4 Hızlı duman testi (5 dk)

Hackathon öncesi tek dosyalık bir test ile şunları doğrula:
- [ ] `import cv2, mediapipe, customtkinter, pystray, pygame, plyer` hatasız çalışıyor
- [ ] `cv2.VideoCapture(0)` kameradan frame okuyor (kamera izni verilmiş)
- [ ] FaceLandmarker modeli yükleniyor ve yüzde 478 nokta dönüyor
- [ ] `pygame.mixer` bir `.wav` çalabiliyor
- [ ] `assets/sounds/` içinde bir alarm sesi var

### 3.5 İşletim sistemi ayarları (benim yapacaklarım)

- Windows: **Ayarlar → Gizlilik ve güvenlik → Kamera** → masaüstü uygulamalarının kameraya erişimi açık
- VS Code: `files.autoSave` = `afterDelay`. Kod Koruyucu git snapshot'ı alır ama kaydedilmemiş editör içeriğini göremez. Bu ayar o boşluğu kapatır. Sunumda da önerilebilir.

---

## 4. Mimari

ESP-IDF projelerimdeki mimari Python'a şu şekilde uyarlanmıştır:

| ESP-IDF (Architecture.md) | Bu proje |
|---|---|
| `libs/<modul>/` component | `libs/<modul>/` Python paketi |
| FreeRTOS task (`xTaskCreate`) | `threading.Thread` (daemon) + ortak `stop_event` |
| `vTaskDelay` | `stop_event.wait(PERIOD_SEC)` (kapanışta anında uyanır) |
| `vTaskDelete(NULL)` | Task fonksiyonundan `return` (thread biter, uygulama çalışmaya devam eder) |
| `Kconfig.projbuild` | `config/default_config.json` |
| `menuconfig` / `sdkconfig` | Ayarlar ekranı / `config/user_config.json` |
| `communicator` (nORB) | `libs/communicator/` (aynı API, `threading.Lock`) |
| `device_state_tracker` + LED'ler | `libs/device_state_tracker/` + tray ikonu ve paneldeki durum göstergeleri |
| `ESP_LOGx(TAG, ...)` | `logging.getLogger(TAG)` |
| `main.c` (ince) | `main.py` (ince) |

### 4.1 Klasör yapısı

```
GDG_PAU_HACKATHON_NightJester/   (proje kökü)
 ├─ PLAN.md                    bu dosya
 ├─ restrictions.md            (varsa) projeye özel kısıtlar
 ├─ README.md                  proje bitince: amaç, ekran görüntüsü, kurulum, kullanım
 ├─ requirements.txt
 ├─ requirements-dev.txt
 ├─ pyproject.toml             Ruff + pytest ayarları
 ├─ .gitignore
 ├─ main.py                    sadece kurulum + task başlatma
 ├─ config/
 │   ├─ default_config.json    şema + varsayılanlar (Kconfig karşılığı)
 │   └─ user_config.json       kullanıcı ayarları (gitignore)
 ├─ assets/
 │   ├─ models/face_landmarker.task
 │   ├─ sounds/alarm.wav
 │   └─ icons/
 ├─ data/                      sessions.db (gitignore)
 ├─ tests/
 │   ├─ test_communicator.py
 │   ├─ test_device_state_tracker.py
 │   └─ test_fatigue_detector.py
 └─ libs/
     ├─ __init__.py
     ├─ communicator/          (zorunlu) task'lar arası pub/sub
     │   ├─ __init__.py
     │   ├─ communicator.py
     │   └─ topics.py
     ├─ device_state_tracker/  (zorunlu) hata bitmask'i + durum göstergeleri
     ├─ config_manager/        ayar yükleme/kaydetme (task değil)
     ├─ camera_capture/        kameradan frame okuma
     ├─ face_analyzer/         MediaPipe → EAR, MAR, yüz var/yok
     ├─ fatigue_detector/      kalibrasyon + durum makinesi (uyanık/uykulu/uyuyor)
     ├─ alert_manager/         moda göre bildirim / alarm / video
     ├─ code_guardian/         git snapshot
     ├─ session_logger/        SQLite olay kaydı + rapor
     └─ ui/                    panel, ayarlar ekranı, tray (ana thread)
         ├─ __init__.py
         ├─ ui.py
         ├─ dashboard.py
         ├─ settings_view.py
         └─ tray.py
```

**İsimlendirme:** Klasör ve ana `.py` dosyası **aynı isimde**, `snake_case` (ör. `libs/face_analyzer/face_analyzer.py`). `__init__.py` modülün public API'sini `__all__` ile dışarı açar.

### 4.2 Veri akışı

```
                ┌──────────────────┐
                │  camera_capture  │ 30 FPS
                └────────┬─────────┘
                    FRAME_TOPIC
             ┌───────────┴───────────┐
             ▼                       ▼
     ┌───────────────┐         ┌──────────┐
     │ face_analyzer │         │    ui    │ (önizleme)
     └───────┬───────┘         └──────────┘
     FACE_METRICS_TOPIC                ▲
             ▼                         │
     ┌──────────────────┐
     │ fatigue_detector │
     └───────┬──────────┘
     FATIGUE_STATE_TOPIC
     ┌───────┼────────────┬────────────────┐
     ▼       ▼            ▼                ▼
 alert_   code_       session_            ui
 manager  guardian    logger

 ui ──APP_MODE / ALERT_COMMAND / CALIBRATION_REQUEST──► ilgili modüller
 device_state_tracker ◄── raise_error / clear_error ── tüm modüller
```

### 4.3 Thread modeli

| Thread | Çalıştığı yer | Periyot | Not |
|---|---|---|---|
| `ui` | **Ana thread** | `after(33 ms)` | Tkinter thread-safe değil. Tüm GUI çağrıları **sadece** burada yapılır. |
| `tray` | `pystray` `run_detached()` | olay tabanlı | Menü tıklamaları topic'e publish eder |
| `device_state_tracker_task` | daemon thread, **ilk başlatılan** | 100 ms | Desenler (yanıp sönme) için hızlı döngü |
| `camera_capture_task` | daemon thread | ~33 ms (kameraya bağlı) | |
| `face_analyzer_task` | daemon thread | yeni frame geldikçe | CPU'yu en çok kullanan modül |
| `fatigue_detector_task` | daemon thread | 100 ms (10 Hz) | |
| `alert_manager_task` | daemon thread | 100 ms | |
| `code_guardian_task` | daemon thread | 500 ms | Git çağrıları bloklayıcı ama nadir |
| `session_logger_task` | daemon thread | 1 s | SQLite bağlantısı **bu thread'de** açılır |

**Kapanış:** `main.py` tek bir `threading.Event` (`stop_event`) oluşturur ve tüm task'lara verir. Pencere kapatıldığında veya tray'den "Çıkış" seçildiğinde `stop_event.set()` çağrılır, thread'ler `join(timeout=2)` ile beklenir.

### 4.4 main.py yapısı

`main.py` **ince** tutulur. Sırayla şunları yapar:

1. Logging kurulumu (format: `zaman [SEVİYE] TAG: mesaj`)
2. `config_manager.load_config()` (bozuksa varsayılana dön + `CONFIG_ERROR`)
3. `advertise_all_topics()`: tüm topic'ler, task'lar başlamadan oluşturulur
4. `device_state_tracker_task` başlatılır (ilk task, böylece sonraki init hataları gösterilebilir)
5. Diğer modül task'ları `threading.Thread(target=..., args=(stop_event,), name=..., daemon=True)` ile başlatılır
6. Tray `run_detached()`
7. `ui.run(stop_event)` → ana thread burada bloklanır
8. Çıkışta `stop_event.set()` ve `join`

```python
"""NightJester giriş noktası. Sadece kurulum ve task başlatma içerir."""

from __future__ import annotations

import logging
import threading

from libs.communicator import orb_advertise
from libs.communicator import topics
from libs.config_manager import load_config
from libs.device_state_tracker import device_state_tracker_task
from libs.camera_capture import camera_capture_task

# ... diğer modüller
from libs.ui import run_ui

TAG = "Main"
log = logging.getLogger(TAG)

THREAD_JOIN_TIMEOUT_SEC = 2.0


def main() -> None:
    _setup_logging()
    log.info("Uygulama başlatıldı")

    config = load_config()
    _advertise_all_topics()

    stop_event = threading.Event()
    tasks = [
        (device_state_tracker_task, "device_state_tracker_task"),  # her zaman ilk
        (camera_capture_task, "camera_capture_task"),
        # ...
    ]
    threads = [_start_task(fn, name, stop_event, config) for fn, name in tasks]

    run_ui(stop_event, config)  # ana thread burada bloklanır

    stop_event.set()
    for t in threads:
        t.join(timeout=THREAD_JOIN_TIMEOUT_SEC)
    log.info("Uygulama kapatıldı")


def _advertise_all_topics() -> None:
    topics.frame_topic = orb_advertise(topics.FRAME_TOPIC)
    # ...


if __name__ == "__main__":
    main()
```

Proje mantığına özel hesaplamalar (EAR, durum makinesi vb.) `main.py`'ye değil, kendi modülüne konur.

### 4.5 communicator (task'lar arası iletişim, zorunlu)

PX4 uORB'den esinlenmiş nORB'nin Python sürümü. Task'lar arası veri **sadece** bununla aktarılır.

**ESP sürümünden bilinçli fark:** ESP'deki `orb_copy` tek abone için tasarlanmıştı. Bu projede `FRAME_TOPIC` ve `FATIGUE_STATE_TOPIC` birden fazla task tarafından okunduğu için her topic bir **sıra numarası** tutar ve her abone kendi gördüğü son numarayı saklar. Böylece aboneler birbirinin `updated` bayrağını sıfırlamaz.

```python
@dataclass
class OrbTopic:
    name: str
    data: Any = None
    seq: int = 0  # her publish'te +1
    lock: threading.Lock = field(default_factory=threading.Lock)


@dataclass
class OrbSubscription:
    topic: OrbTopic
    last_seq: int = 0


def orb_advertise(name: str) -> OrbTopic: ...
def orb_publish(topic: OrbTopic, data: Any) -> bool: ...  # veriyi kopyalar, seq += 1
def orb_subscribe(topic: OrbTopic) -> OrbSubscription: ...  # her okuyan task kendi aboneliğini alır
def orb_copy(sub: OrbSubscription) -> tuple[bool, Any]: ...  # (yeni veri var mı, son veri)
```

- `orb_publish` veriyi `copy.copy` ile, NumPy frame'leri için `ndarray.copy()` ile kopyalar. Okuyan taraf yayınlayanın tamponunu değiştiremez.
- `orb_copy` her zaman son veriyi döner (yoksa `None`). `bool` değeri, abonenin son okumasından beri yeni veri gelip gelmediğini gösterir.
- Abonelik, task'ın init fonksiyonunda oluşturulur.

**topics.py:** Topic isimleri, handle'lar ve veri tipleri **tek dosyada** tanımlanır. Her topic'in yanına **yayınlayan → okuyan** yazılır.

```python
# TOPIC İSİMLERİ
FRAME_TOPIC = "frame"
FACE_METRICS_TOPIC = "face_metrics"
FATIGUE_STATE_TOPIC = "fatigue_state"
APP_MODE_TOPIC = "app_mode"
ALERT_COMMAND_TOPIC = "alert_command"
CALIBRATION_REQUEST_TOPIC = "calibration_request"
GUARDIAN_RESULT_TOPIC = "guardian_result"
CONFIG_UPDATED_TOPIC = "config_updated"

# TOPICS (main.py'deki advertise_all_topics içinde atanır)
frame_topic: OrbTopic | None = None  # camera_capture → face_analyzer, ui
face_metrics_topic: OrbTopic | None = None  # face_analyzer → fatigue_detector, ui
fatigue_state_topic: OrbTopic | None = (
    None  # fatigue_detector → alert_manager, code_guardian, session_logger, ui
)
app_mode_topic: OrbTopic | None = None  # ui, tray → fatigue_detector, alert_manager, code_guardian
alert_command_topic: OrbTopic | None = None  # ui, tray → alert_manager
calibration_request_topic: OrbTopic | None = None  # ui → fatigue_detector
guardian_result_topic: OrbTopic | None = None  # code_guardian → ui, session_logger
config_updated_topic: OrbTopic | None = None  # ui → fatigue_detector, alert_manager, code_guardian


# TYPES
class AppMode(Enum):
    NORMAL = auto()
    DEADLINE = auto()
    PAUSED = auto()


class FatigueLevel(Enum):
    AWAKE = auto()
    DROWSY = auto()
    ASLEEP = auto()
    NO_FACE = auto()
    CALIBRATING = auto()


@dataclass
class Frame:
    image: np.ndarray  # BGR
    timestamp_ms: int


@dataclass
class FaceMetrics:
    face_present: bool
    ear: float  # iki gözün ortalaması
    mar: float
    timestamp_ms: int
    landmarks_px: np.ndarray | None = None  # önizleme overlay'i için (opsiyonel)


@dataclass
class FatigueState:
    level: FatigueLevel
    score: int  # 0–100
    eyes_closed_sec: float
    perclos: float  # 0.0–1.0
    ear_threshold: float
    timestamp_ms: int


@dataclass
class AlertCommand:
    action: str  # "stop" | "test"


@dataclass
class GuardianResult:
    success: bool
    repo_path: str
    message: str
    timestamp_ms: int
```

### 4.6 device_state_tracker (zorunlu)

Uygulamanın tüm **kritik hata durumları tek bir bitmask'te** tutulur. **Durum göstergeleri sadece bu modül tarafından sürülür.**

**Kurallar:**
- Hatalar `enum.IntFlag` ile tanımlanır, her biri **tek bit**. Kullanılmayan bitler "rezerve" yorumuyla bırakılır. 8 hata ile sınırlı tutulur (ESP'deki `uint8_t` disiplininin karşılığı).
- Sadece **kritik** hatalar listeye alınır (init + bağlantı hataları). "Yüz görünmüyor" gibi durumlar hata **değildir**.
- Hata olmayan durum bilgileri bitmask'e değil, `DeviceState` dataclass'ındaki ayrı alanlara konur (`calibrated`, `alarm_active` vb.).
- Erişim **sadece** `raise_error()`, `clear_error()`, `get_error_status()`, `get_error_mask()` ile yapılır. Bunlar `threading.Lock` ile korunur.
- Bitmask değiştiğinde log'a yazılır (`ESP_LOGW` karşılığı `log.warning`).

**Gösterge politikası (LED politikasının karşılığı):**
- Normal çalışmada hata göstergeleri **sönük (gri)**, sadece hata varken renklenir. Kullanıcının dikkati dağılmaz.
- Gösterge sayısı minimumda: **alt sistem başına 1 gösterge** (panelin altında 3 nokta):
  - **Görüntü** (kamera + model)
  - **Uyarı** (ses / medya)
  - **Entegrasyon** (git + config)
- Aynı göstergedeki farklı hatalar **desenle** ayrılır: sürekli yanık (en kritik), hızlı yanıp sönme (200 ms), yavaş yanıp sönme (1 s). Birden fazla hata varsa öncelikli olanın deseni gösterilir.
- Açılışta tüm göstergeler ~300 ms yanar (lamba testi, demo'da da hoş durur).
- **Tray ikonu rengi** yorgunluk durumunu gösterir (yeşil: uyanık, sarı: uykulu, kırmızı: uyuyor, gri: duraklatıldı / yüz yok). Herhangi bir kritik hata varsa ikon üstünde ünlem gösterilir.

Desen hesaplaması bu modülde yapılır. Modül, her gösterge için `on/off` durumunu bir topic'e değil, `get_indicator_states()` fonksiyonuyla UI'ya açar. UI bunu her `after()` döngüsünde okur.

```python
class DeviceError(IntFlag):
    NO_ERROR = 0x00
    CAMERA_INIT_ERROR = 0x01  # Kamera açılamadı
    CAMERA_READ_ERROR = 0x02  # Kameradan frame okunamıyor (bağlantı koptu)
    MODEL_LOAD_ERROR = 0x04  # FaceLandmarker modeli yüklenemedi
    AUDIO_INIT_ERROR = 0x08  # pygame.mixer başlatılamadı
    GIT_ERROR = 0x10  # Git bulunamadı / repo geçersiz
    CONFIG_ERROR = 0x20  # Config okunamadı, varsayılana dönüldü
    # 0x40                       rezerve
    # 0x80                       rezerve
```

### 4.7 config_manager (Kconfig karşılığı)

- Tüm eşikler, süreler, kamera indeksi, dosya yolları ve medya seçimleri **config'den gelir**. Kodda sihirli sayı olmaz.
- `default_config.json` tek üst nesnedir. Altında **modül başına bir bölüm** bulunur.
- `load_config()` önce varsayılanı, sonra varsa `user_config.json`'u okur ve üstüne yazar (deep merge). Sonuç tipli dataclass'lara dönüştürülür.
- Modüller config değerini **doğrudan kullanmaz**. Init'te anlamlı bir modül sabitine bağlar (`#define` karşılığı):

```python
# libs/fatigue_detector/fatigue_detector.py
def _load_settings(cfg: FatigueConfig) -> None:
    global _EAR_CLOSED_RATIO, _DROWSY_CLOSED_SEC, _ASLEEP_CLOSED_SEC
    _EAR_CLOSED_RATIO = cfg.ear_closed_ratio
    _DROWSY_CLOSED_SEC = cfg.drowsy_closed_sec
    _ASLEEP_CLOSED_SEC = cfg.asleep_closed_sec
```

- Ayarlar ekranından kaydedilen değişiklikler `CONFIG_UPDATED_TOPIC`'e publish edilir. Eşik ve medya ayarları anında güncellenir. Kamera indeksi gibi donanım ayarları **yeniden başlatma** gerektirir (UI bunu kullanıcıya söyler).

Şablon (`config/default_config.json`):

```json
{
  "camera": {
    "index": 0,
    "width_px": 640,
    "height_px": 480,
    "target_fps": 30
  },
  "face_analyzer": {
    "model_path": "assets/models/face_landmarker.task",
    "min_detection_confidence": 0.5
  },
  "fatigue_detector": {
    "calibration_duration_sec": 5.0,
    "ear_closed_ratio": 0.75,
    "drowsy_closed_sec": 1.5,
    "asleep_closed_sec": 3.0,
    "perclos_window_sec": 60.0,
    "perclos_drowsy_threshold": 0.25,
    "yawn_mar_threshold": 0.6,
    "yawn_min_duration_sec": 1.0,
    "no_face_timeout_sec": 5.0,
    "awake_recovery_sec": 2.0
  },
  "alert_manager": {
    "normal_mode_cooldown_sec": 600,
    "voice_dir": "def_voice_files",
    "voice_gender": "female",
    "deadline_media_type": "sound",
    "deadline_sound_path": "",
    "deadline_video_urls": [],
    "deadline_video_path": "",
    "deadline_sound_with_video": false,
    "volume_start": 0.4,
    "volume_step": 0.15,
    "volume_step_interval_sec": 5.0
  },
  "code_guardian": {
    "enabled": true,
    "repo_paths": [],
    "min_interval_sec": 300
  },
  "session_logger": {
    "db_path": "data/sessions.db"
  },
  "ui": {
    "start_mode": "NORMAL",
    "show_landmarks": true,
    "start_minimized": false
  }
}
```

### 4.8 Modül kuralları

Her modül şu yapıyı izler:

- **Public API** `__init__.py`'de `__all__` ile açılır. Her public fonksiyonun Türkçe docstring'i olur.
- **Ana iş bir task fonksiyonudur:** `def <modul>_task(stop_event: threading.Event, config: AppConfig) -> None`. Task önce kendi `_init()` fonksiyonunu çağırır, sonra `while not stop_event.is_set():` döngüsüne girer. Döngüde her zaman bir bekleme olur (`stop_event.wait(...)` veya bloklayan bir okuma).
- Init başarısızsa ilgili hata `raise_error(...)` ile kaldırılır, başarılıysa `clear_error(...)` ile temizlenir. Kritik init hatasında task `log.error` ile sebebi yazıp `return` ile biter. **Uygulama çökmez.**
- Dosya başında `TAG = "<ModulAdi>"` ve `log = logging.getLogger(TAG)` bulunur. Log mesajları Türkçedir.
- Modül içi yardımcı fonksiyonlar ve değişkenler `_` önekli (private) olur.
- Harici çağrılar (kamera, model, dosya, subprocess, pygame) `try/except <SpesifikHata>` ile sarılır. `except Exception` sadece task'ın en dış koruması olarak kullanılır ve hata loglanır.
- Modüller birbirinin değişkenine doğrudan erişmez. Veri alışverişi **`communicator`**, hata bilgisi **`device_state_tracker`** üzerinden yapılır.
- Modül, `ui` dışında hiçbir GUI kütüphanesini import etmez.

**Modül şablonu** (`libs/<modul>/<modul>.py`):

```python
"""<Modul> modülü: <tek cümlelik açıklama>."""
from __future__ import annotations

import logging
import threading

from libs.communicator import orb_copy, orb_publish, orb_subscribe
from libs.communicator import topics
from libs.config_manager import AppConfig
from libs.device_state_tracker import DeviceError, clear_error, raise_error

TAG = "<ModulAdi>"
log = logging.getLogger(TAG)

LOOP_PERIOD_SEC = 0.1

_PIN_LIKE_SETTING: int = 0          # init'te config'den doldurulur
_input_sub = None


def <modul>_task(stop_event: threading.Event, config: AppConfig) -> None:
    """<Modul> task'ı. Init eder ve <ne yaptığı> döngüsünü çalıştırır.

    Args:
        stop_event: Uygulama kapanırken set edilen ortak olay.
        config: Uygulama ayarları.
    """
    if not _init(config):
        log.error("<Modul> başlatılamadı, task sonlandırılıyor.")
        return

    try:
        while not stop_event.is_set():
            updated, data = orb_copy(_input_sub)
            if updated:
                _process(data)
            stop_event.wait(LOOP_PERIOD_SEC)
    except Exception:
        log.exception("Beklenmeyen hata, task sonlandırılıyor.")
    finally:
        _deinit()


def _init(config: AppConfig) -> bool:
    global _input_sub
    try:
        # ... kaynak açma ...
        _input_sub = orb_subscribe(topics.some_topic)
    except OSError as err:
        log.error("Init hatası: %s", err)
        raise_error(DeviceError.<MODUL>_INIT_ERROR)
        return False
    clear_error(DeviceError.<MODUL>_INIT_ERROR)
    return True


def _process(data) -> None:
    ...


def _deinit() -> None:
    """Kaynakları serbest bırakır (kamera, dosya, mixer vb.)."""
```

**`__init__.py` şablonu:**

```python
from .<modul> import <modul>_task

__all__ = ["<modul>_task"]
```

### 4.9 Modül sorumlulukları

| Modül | Sorumluluk | Okur | Yayınlar |
|---|---|---|---|
| `camera_capture` | Kamerayı açar, çözünürlüğü ayarlar, frame'i yatay çevirir (ayna) | — | `FRAME` |
| `face_analyzer` | FaceLandmarker'ı **VIDEO** modunda çalıştırır (`detect_for_video`, artan timestamp). EAR, MAR, yüz var/yok hesaplar. | `FRAME` | `FACE_METRICS` |
| `fatigue_detector` | Kalibrasyon, kayan pencere (PERCLOS), esneme sayacı, durum makinesi | `FACE_METRICS`, `APP_MODE`, `CALIBRATION_REQUEST`, `CONFIG_UPDATED` | `FATIGUE_STATE` |
| `alert_manager` | Moda göre bildirim / ses (artan ses seviyesi) / video linki / lokal video. Cooldown, durdurma komutu. | `FATIGUE_STATE`, `APP_MODE`, `ALERT_COMMAND`, `GUARDIAN_RESULT`, `CONFIG_UPDATED` | — (`DeviceState.alarm_active` günceller) |
| `code_guardian` | Deadline modunda `ASLEEP` geçişinde repo(lar)da değişiklik varsa snapshot alır | `FATIGUE_STATE`, `APP_MODE`, `CONFIG_UPDATED` | `GUARDIAN_RESULT` |
| `session_logger` | Seviye geçişlerini ve guardian sonuçlarını SQLite'a yazar, `get_hourly_report()` sağlar | `FATIGUE_STATE`, `GUARDIAN_RESULT` | — |
| `ui` | Panel (önizleme + overlay, EAR grafiği, durum, mod anahtarı, "Uyandım", "Kalibre et", "Test alarmı"), ayarlar ekranı, rapor, tray | `FRAME`, `FACE_METRICS`, `FATIGUE_STATE`, `GUARDIAN_RESULT` | `APP_MODE`, `ALERT_COMMAND`, `CALIBRATION_REQUEST`, `CONFIG_UPDATED` |

**Kod Koruyucu komutları** (çalışma alanını değiştirmez):

```bash
git -C <repo> status --porcelain            # değişiklik var mı?
git -C <repo> stash create                  # çıktı: commit SHA (boşsa değişiklik yok)
git -C <repo> stash store -m "nightjester: uyku anı <zaman>" <SHA>
```

> Not: `git stash create` takip edilmeyen (untracked) dosyaları kapsamaz. Demo'da bu belirtilir. Geri yükleme: `git stash list` → `git stash apply stash@{n}`.

---

## 5. Tespit Algoritması

### 5.1 Ölçümler

**EAR (Eye Aspect Ratio):** göz açıklık oranı. Göz kapandıkça 0'a yaklaşır.

```
EAR = (|p2 − p6| + |p3 − p5|) / (2 · |p1 − p4|)
```

MediaPipe Face Mesh indeksleri (478 noktalı model):

| Göz | p1 | p2 | p3 | p4 | p5 | p6 |
|---|---|---|---|---|---|---|
| Sol | 33 | 160 | 158 | 133 | 153 | 144 |
| Sağ | 362 | 385 | 387 | 263 | 373 | 380 |

**MAR (Mouth Aspect Ratio):** esneme tespiti için. Dikey: 13–14, yatay: 61–291.

> Noktalar normalize (0–1) gelir. Mesafe hesabından önce piksele çevrilir (`x · width`, `y · height`), yoksa en-boy oranı EAR'ı bozar.
> İndeksler implementasyonda bir kez görsel olarak doğrulanmalı (noktaları frame üstüne çizerek).

**Yedek / doğrulama:** FaceLandmarker `output_face_blendshapes=True` ile `eyeBlinkLeft/Right` ve `jawOpen` skorlarını da verir. Birincil ölçüm EAR'dır (sunumda formül anlatılabilir). Blendshape'ler debug panelinde gösterilebilir.

### 5.2 Kalibrasyon

1. Kullanıcıya "5 saniye boyunca normal şekilde ekrana bak" denir (`CALIBRATING` durumu).
2. Bu sürede ölçülen EAR'ların **medyanı** = `baseline_ear` (göz kırpmalara karşı dayanıklı).
3. `ear_threshold = baseline_ear × ear_closed_ratio` (varsayılan 0,75).
4. Kalibrasyon yapılmadan tespit başlamaz. İlk açılışta otomatik çalışır, "Kalibre et" butonuyla tekrarlanır.

### 5.3 Durum makinesi

```
              kalibrasyon bitti
CALIBRATING ───────────────────► AWAKE
                                  │ ▲
       gözler ≥ drowsy_closed_sec │ │ gözler açık ≥ awake_recovery_sec
     veya PERCLOS > eşik          │ │
     veya son 5 dk'da ≥ 3 esneme  ▼ │
                                 DROWSY
                                  │ ▲
       gözler ≥ asleep_closed_sec │ │ gözler açık ≥ awake_recovery_sec
   veya DROWSY iken yüz kayboldu  ▼ │
                                 ASLEEP

 Herhangi bir durumda yüz no_face_timeout_sec boyunca yok → NO_FACE
 (istisna: DROWSY iken yüz kaybolursa → ASLEEP; kafa masaya düşmüş olabilir)
```

- **Göz kırpma filtresi:** `eyes_closed_sec`, EAR eşiğin altında kaldığı **kesintisiz** süredir. Normal göz kırpma (~100–400 ms) `drowsy_closed_sec` (1,5 s) altında kaldığı için tetiklemez.
- **PERCLOS:** son `perclos_window_sec` içinde gözlerin kapalı olduğu frame oranı.
- **Aşağı bakma riski:** Klavyeye veya dokümana bakarken EAR düşük ölçülebilir. Bu yüzden eşik kalibrasyonla kişiye göre belirlenir ve `drowsy_closed_sec` kısa göz kısmalarını filtreler. Demo ortamında yanlış alarm oranı test edilir ([Bölüm 10](#10-varsayımlar-ve-açık-konular), madde 9).
- **Skor (0–100):** panelde gösterilecek tek sayı. Örnek ağırlıklar: `eyes_closed_sec`, PERCLOS ve esneme sayısından. Formül implementasyonda belirlenir ve `fatigue_detector.py` içinde sabitlerle tanımlanır.
- `PAUSED` modunda tespit çalışır ama durum `AWAKE` olarak yayınlanır, alarm çalmaz.

### 5.4 Moda göre tepki

| Seviye | Normal mod | Deadline modu |
|---|---|---|
| DROWSY | Bildirim: "Yorgun görünüyorsun, 5 dk mola?" + `Drowsy/` sesi (cooldown) | Aynı `Drowsy/` sesi (bildirimsiz) |
| ASLEEP | Bildirim: "Uyumak verimlilik için en iyi yatırım" + `Sleepy/normal/` sesi (cooldown) | Seçilen medya oynatılır. Ses seviyesi kademeli artar. Kod Koruyucu tetiklenir. |
| AWAKE'e dönüş | — | Ses durur. "Hoş geldin" bildirimi (Faz_5'ten sonra: "kodun güvende"). |

**Ses dosyaları** (`voice_dir` / `voice_gender`): `def_voice_files/<female|male>/Drowsy/`, `.../Sleepy/normal/`, `.../Sleepy/deadline/`. Her klasördeki `.wav/.ogg/.mp3` dosyalarından **rastgele** biri çalınır, klasöre dosya eklemek yeterlidir. (`.m4a` pygame tarafından desteklenmez, `.ogg`'ye çevrilmelidir. Çevrilmemiş dosya varsa açılışta log'a uyarı yazılır.)

**Deadline alarm sesi seçim sırası:** `deadline_sound_path` (doluysa) → `Sleepy/deadline/` içinden rastgele → `Sleepy/normal/` içinden rastgele.

**Deadline medya tipi** (`deadline_media_type`): `sound` | `video_url` (`deadline_video_urls` listesinden **rastgele** bir link tarayıcıda açılır) | `video_file` (`deadline_video_path`). Varsayılan olarak (`deadline_sound_with_video: false`) **sadece** video açılır. `true` yapılırsa video ile birlikte alarm sesi de çalar. Video açılamazsa (liste boş, dosya yok, tarayıcı açılmadı) uyandırma garanti olsun diye alarm sesi çalar.

---

## 6. Hata Bitmask Tablosu

| Bit | Değer | Hata | Anlamı | Gösterge | Desen | Öncelik (gösterge içi) |
|---|---|---|---|---|---|---|
| 0 | 0x01 | `CAMERA_INIT_ERROR` | Kamera açılamadı (izin yok / başka uygulama kullanıyor / yanlış indeks) | Görüntü | Sürekli | 1 |
| 1 | 0x02 | `CAMERA_READ_ERROR` | Kameradan art arda N frame okunamadı | Görüntü | Hızlı (200 ms) | 2 |
| 2 | 0x04 | `MODEL_LOAD_ERROR` | `face_landmarker.task` bulunamadı / yüklenemedi | Görüntü | Yavaş (1 s) | 3 |
| 3 | 0x08 | `AUDIO_INIT_ERROR` | `pygame.mixer` başlatılamadı veya ses dosyası yok | Uyarı | Sürekli | 1 |
| 4 | 0x10 | `GIT_ERROR` | `git` bulunamadı veya repo yolu geçersiz | Entegrasyon | Hızlı (200 ms) | 2 |
| 5 | 0x20 | `CONFIG_ERROR` | `user_config.json` bozuk, varsayılan kullanılıyor | Entegrasyon | Sürekli | 1 |
| 6 | 0x40 | — | Rezerve | — | — | — |
| 7 | 0x80 | — | Rezerve | — | — | — |

---

## 7. Kod Biçimi

| Konu | Kural |
|---|---|
| Dil | Yorumlar, docstring'ler ve log mesajları **Türkçe**. Tanımlayıcılar (fonksiyon, değişken, sınıf) **İngilizce**. |
| İsimlendirme | Fonksiyon/değişken/modül `snake_case`, sabit ve enum üyeleri `UPPER_SNAKE_CASE`, sınıf/dataclass `PascalCase` (PEP 8; ESP'deki `_t` son eki Python'da kullanılmaz) |
| Private | Modül içi fonksiyon ve değişkenler `_` önekli |
| Task isimleri | `<modul>_task`. `threading.Thread(name=...)` değeri fonksiyon adıyla aynı. |
| Tip ipuçları | Tüm public fonksiyonlarda zorunlu. Her dosyanın başında `from __future__ import annotations`. |
| Docstring | Google stili, Türkçe. İlk satır tek cümlelik özet (`@brief` karşılığı). Gerekirse `Args:`, `Returns:`, `Raises:` |
| Yorumlar | `.py` içinde sadece "neden" yorumları. "Ne yaptığını" kod ve docstring anlatır. |
| Sabitler | Sihirli sayı yok. Birimi belli isimler: `_SEC`, `_MS`, `_HZ`, `_PX` son ekleri (`LOOP_PERIOD_SEC`, `BLINK_FAST_MS`) |
| Log | `log = logging.getLogger(TAG)`. f-string değil `%s` formatı (`log.info("EAR: %.3f", ear)`). Döngü içindeki yüksek frekanslı log'lar `debug` seviyesinde. |
| Hata yönetimi | Spesifik exception yakalanır. Çıplak `except:` yasak. Hata yutulmaz: ya loglanır + `raise_error`, ya yukarı fırlatılır. |
| Bekleme | `time.sleep` yerine `stop_event.wait(...)` |
| Thread güvenliği | Paylaşılan durum sadece `communicator` ve `device_state_tracker` üzerinden. GUI çağrıları sadece ana thread'de. |
| Format / lint | Ruff, satır uzunluğu 100, `ruff format` + `ruff check` temiz olmalı |
| Import sırası | stdlib → üçüncü parti → `libs.*` (Ruff `I` kuralı düzenler) |
| Yollar | `pathlib.Path`, proje köküne göre çözülür. Sabit mutlak yol yok. |

**`pyproject.toml` (Ruff + pytest):**

```toml
[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "B", "UP"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

**Yapılmayacaklar:**
- Worker thread'den Tkinter / CustomTkinter widget'ına dokunulmaz (çökme veya donma sebebi).
- `cv2.imshow` kullanılmaz. Önizleme sadece UI'da gösterilir.
- Kamera frame'i diske yazılmaz, ağ üzerinden gönderilmez.
- Kod Koruyucu `git stash push`, `git commit`, `git reset` gibi çalışma alanını veya geçmişi değiştiren komutlar çalıştırmaz.
- Uyarıyı "duyurmak" için task içinde saniyelerce bekleme yapılmaz. Durum bilgisi topic'ten okunur.
- Config değeri modül içinde doğrudan `config.x.y` diye her yerde okunmaz. Init'te modül sabitine bağlanır.

---

## 8. Geliştirme Planı (5–5,5 saat)

Her faz sonunda uygulama **çalışır durumda** olmalı. Testleri ben yaparım, commit'leri ben atarım.

### 8.1 Fazlar

| Faz | Süre | Kümülatif | Kapsam |
|---|---|---|---|
| **Faz_1** | 0:30 | 0:30 | **İskelet:** klasör yapısı, `pyproject.toml`, `requirements*.txt`, `.gitignore`, `config_manager`, `communicator`, `device_state_tracker`, ince `main.py`, logging, birim testleri |
| **Faz_2** | 0:45 | 1:15 | **Görüntü hattı:** `camera_capture` + `face_analyzer` (EAR, MAR) + minimal UI penceresi (önizleme + göz noktaları + EAR değeri) |
| **Faz_3** | 0:45 | 2:00 | **Tespit:** `fatigue_detector` (kalibrasyon, kesintisiz kapalı göz süresi, durum makinesi), UI'da durum etiketi + "Kalibre et" butonu |
| **Faz_4** | 0:45 | 2:45 | **Uyarılar:** `alert_manager` (Normal: plyer bildirimi + cooldown; Deadline: ses döngüsü + artan ses + video URL/dosya), mod anahtarı, "Uyandım" ve "Test alarmı" butonları |
| 🎯 | — | **2:45** | **MVP / DEMO HAZIR NOKTASI.** Bu noktadan sonra demo her an yapılabilir durumda olmalı. |
| **Faz_5** | 0:30 | 3:15 | **Kod Koruyucu:** `code_guardian` + UI'da son snapshot bilgisi |
| **Faz_6** | 0:30 | 3:45 | **Arka plan:** `pystray` tray (renkli ikon, mod değiştirme, göster/gizle, çıkış), pencereyi kapatınca tray'e küçülme |
| **Faz_7** | 0:20 | 4:05 | **Akıllandırma:** PERCLOS, esneme sayacı, NO_FACE / kafa düşmesi kuralı, 0–100 skor |
| **Faz_8** | 0:30 | 4:35 | **Cila:** ayarlar ekranı (medya seçimi, eşikler, repo yolu), canlı EAR grafiği, durum göstergeleri + lamba testi, `session_logger` + basit saatlik rapor |
| **Faz_9** | 0:30–0:45 | 5:05–5:20 | **Sağlamlaştırma + demo provası:** hata senaryoları, demo ortamında eşik ayarı, README, demo senaryosunun 2 kez provası |

### 8.2 Faz Sonu Raporu şablonu

AI asistan her fazın sonunda **tam olarak** bu formatta yazar ve onay bekler:

```markdown
## Faz_x Sonu Raporu: <faz adı>

**Yapılanlar:**
- <oluşturulan / değiştirilen dosyalar ve kısa açıklama>

**Planın dışına çıkılan / varsayım yapılan noktalar:**
- <yoksa "Yok">

**Test etmen gerekenler:**
1. [ ] <adım>: `<çalıştırılacak komut>` → **Beklenen:** <ne görülmeli>
2. [ ] ...

**Bilinen eksikler / sonraki fazlara bırakılanlar:**
- <yoksa "Yok">

⏸ Onayını bekliyorum. Testler geçtiyse "Faz_x onaylandı" yaz.
```

### 8.3 Faz test listeleri

Bunlar her fazın **bitti sayılma kriterleridir**. AI asistan Faz Sonu Raporu'nda bunları komut ve beklenen sonuçla birlikte adım adım verir. Gerekirse fazın içeriğine göre test ekleyebilir ama listeden test çıkaramaz.

**Faz_1: İskelet**
1. `python main.py` hatasız açılıyor. Log'da her task için "başlatıldı" satırı var ve `device_state_tracker_task` ilk sırada.
2. Uygulama `Ctrl+C` (veya geçici kapatma yöntemi) ile kapanıyor. Log'da "kapatıldı" satırı var, terminal askıda kalmıyor.
3. `config/user_config.json` yokken varsayılanlarla açılıyor. Dosyayı bozuk JSON yapınca çökmüyor, log'da `CONFIG_ERROR` uyarısı çıkıyor.
4. `pytest` → `test_communicator.py` ve `test_device_state_tracker.py` geçiyor (çok abone, sıra numarası, bitmask set/clear testleri).
5. `ruff check .` ve `ruff format --check .` temiz.

**Faz_2: Görüntü hattı**
1. Pencere açılıyor, canlı ve aynalanmış kamera görüntüsü akıyor.
2. Göz noktaları yüzün üstünde doğru yerlerde çiziliyor (indeks doğrulaması).
3. Gözler açıkken EAR yaklaşık sabit. Gözleri kapatınca belirgin şekilde düşüyor. Ağzı açınca MAR artıyor.
4. Yüz kadrajdan çıkınca "yüz yok" gösteriliyor, uygulama çökmüyor.
5. `config` içinde kamera indeksini olmayan bir değere ayarlayınca çökmüyor, log'da `CAMERA_INIT_ERROR` var.
6. Model dosyasının adını geçici olarak değiştirince çökmüyor, log'da `MODEL_LOAD_ERROR` var.
7. Uygulama kapanınca kamera ışığı sönüyor.

**Faz_3: Tespit**
1. Açılışta 5 sn kalibrasyon yapılıyor. Baseline EAR ve eşik log'a yazılıyor.
2. Normal göz kırpma durumu değiştirmiyor (AWAKE kalıyor).
3. Gözleri ~1,5 sn kapatınca DROWSY, ~3 sn kapatınca ASLEEP oluyor.
4. Gözleri açınca ~2 sn içinde AWAKE'e dönüyor.
5. Klavyeye / masaya bakarken yanlış DROWSY oluşup oluşmadığı gözlemleniyor. Sonuç not edilir.
6. "Kalibre et" butonu kalibrasyonu yeniden başlatıyor.
7. `pytest` → `test_fatigue_detector.py` (sentetik EAR dizileriyle durum geçişleri) geçiyor.

**Faz_4: Uyarılar**
1. Normal modda DROWSY → masaüstü bildirimi geliyor. Cooldown süresi dolmadan tekrar gelmiyor.
2. Deadline modunda ASLEEP → seçili ses döngüde çalıyor, ses seviyesi kademeli artıyor.
3. Gözler açılıp AWAKE'e dönünce alarm kendiliğinden duruyor.
4. "Uyandım" butonu alarmı anında durduruyor.
5. `deadline_media_type` değerini `video_url` yapınca link tarayıcıda açılıyor. `video_file` yapınca lokal video oynatıcıda açılıyor.
6. Ses dosyası yokken çökmüyor, log'da `AUDIO_INIT_ERROR` var.
7. "Test alarmı" butonu tespitten bağımsız olarak alarmı çalıyor.

**Faz_5: Kod Koruyucu**
1. Test reposunda kaydedilmiş ama commit'lenmemiş bir değişiklik varken Deadline modunda ASLEEP olunca `git stash list`'te `nightjester: uyku anı …` kaydı oluşuyor.
2. `git status` çıktısı snapshot öncesiyle **aynı** (çalışma alanı değişmemiş).
3. Repoda değişiklik yokken yeni stash kaydı oluşmuyor.
4. `min_interval_sec` dolmadan ikinci snapshot alınmıyor.
5. Normal modda snapshot alınmıyor.
6. Geçersiz repo yolu verilince çökmüyor, log'da `GIT_ERROR` var.
7. UI'da son snapshot bilgisi (zaman + repo) görünüyor.

**Faz_6: Arka plan**
1. Tray ikonu görünüyor, rengi duruma göre değişiyor (yeşil / sarı / kırmızı / gri).
2. Tray menüsünden mod değiştirince UI'daki mod anahtarı da güncelleniyor (ve tersi).
3. Pencereyi kapatınca uygulama kapanmıyor, tray'e küçülüyor.
4. Pencere gizliyken Deadline modunda ASLEEP olunca alarm çalıyor.
5. Tray'den "Göster" pencereyi geri getiriyor. "Çıkış" uygulamayı temiz kapatıyor (kamera ışığı sönüyor).

**Faz_7: Akıllandırma**
1. Kısa sürede art arda esneyince esneme sayacı artıyor. Eşik aşılınca DROWSY oluyor.
2. Gözleri sık sık uzun kırpınca PERCLOS yükseliyor ve eşik aşılınca DROWSY oluyor.
3. DROWSY iken kafa kadrajdan çıkınca ASLEEP oluyor.
4. AWAKE iken kadrajdan çıkınca (masadan kalkma) NO_FACE oluyor, alarm çalmıyor.
5. Skor (0–100) panelde görünüyor ve durumla tutarlı değişiyor.

**Faz_8: Cila**
1. Ayarlar ekranından medya tipi ve dosya/link seçimi kaydediliyor. Değişiklik yeniden başlatmadan etkili oluyor.
2. Eşik değiştirilince (ör. `drowsy_closed_sec`) tespit davranışı anında değişiyor.
3. Kamera indeksi değiştirilince "yeniden başlatma gerekli" uyarısı çıkıyor.
4. Canlı EAR grafiği akıyor, eşik çizgisi görünüyor.
5. Açılışta durum göstergeleri ~300 ms yanıyor (lamba testi). Hata yokken gri kalıyorlar.
6. Bir hata oluşturulunca (ör. ses dosyasını sil) ilgili gösterge doğru desenle yanıyor.
7. Rapor ekranında oturumdaki DROWSY / ASLEEP olayları saatlere göre görünüyor.

**Faz_9: Sağlamlaştırma + demo provası**
1. [Bölüm 9.1](#91-teknik-doğrulama)'deki teknik doğrulama listesinin tamamı.
2. Demo ortamında (ışık, gözlük) yeniden kalibrasyon ve eşik kontrolü.
3. README'deki kurulum adımları temiz bir terminalde takip edilerek uygulama açılabiliyor.
4. [Bölüm 9.2](#92-demo-akışı-3-dk)'deki demo akışı baştan sona 2 kez sorunsuz.

### 8.4 Zaman kontrol noktaları

- **1:15'te** (Faz_2 sonu) canlı EAR görünmüyorsa: overlay'i ve UI'ı bırak, EAR'ı terminale yazdır, Faz_3'e geç.
- **2:45'te** (Faz_4 sonu) MVP hazır değilse: Faz_5–Faz_8'i atla, doğrudan Faz_9'a geç.
- **4:05'te** (Faz_7 sonu) geride isen: Faz_8'den sadece ayarlar ekranının **medya seçimi** kısmını yap.

### 8.5 Kesme listesi

Zaman daralırsa **sondan başa** doğru kesilir:

1. Saatlik rapor ekranı (`session_logger` sadece kayıt yapsın)
2. Canlı EAR grafiği
3. Esneme sayacı
4. Ayarlar ekranı → JSON'dan düzenleme ile idare edilir
5. PERCLOS (sadece kesintisiz kapalı göz süresi kalır)
6. Tray (sadece pencere modu)

**Asla kesilmeyenler:** kalibrasyon, iki mod, Deadline alarmı, Kod Koruyucu (projenin farkı bu).

---

## 9. Doğrulama ve Demo Senaryosu

### 9.1 Teknik doğrulama

- [ ] `ruff check .` ve `ruff format --check .` temiz
- [ ] `pytest` geçiyor (communicator, device_state_tracker, fatigue_detector durum makinesi)
- [ ] Kamera takılı değilken uygulama çökmüyor, Görüntü göstergesi sürekli yanıyor
- [ ] Model dosyası yokken uygulama çökmüyor, Görüntü göstergesi yavaş yanıp sönüyor
- [ ] Gözlükle test edildi
- [ ] Demo salonuna benzer ışıkta test edildi (gerekirse yeniden kalibrasyon)
- [ ] CPU kullanımı makul (gerekirse analiz FPS'i düşürülür)
- [ ] Uygulama kapatıldığında kamera serbest kalıyor (ışığı sönüyor)

### 9.2 Demo akışı (~3 dk)

1. **Problem (20 sn):** "Deadline gecesi saat 03:00, klavyenin üstünde uyuyakaldın. Kaydedilmemiş iş ve kaçan saatler."
2. **Açılış + kalibrasyon (20 sn):** Uygulamayı aç, lamba testi, 5 sn kalibrasyon. EAR değerini ve formülü göster.
3. **Normal mod (30 sn):** Gözleri 2 sn kapat → DROWSY → nazik bildirim.
4. **Deadline modu (60 sn):** Modu değiştir, kafayı masaya düşür → ASLEEP → alarm / video çalar, ses yükselir. Uyan → alarm durur, "kodun güvende" bildirimi. Terminalde `git stash list` ile snapshot'ı göster.
5. **Akıllı kısım (30 sn):** Normal göz kırpmanın alarm tetiklemediğini ve esneme sayacını göster. DROWSY iken kafayı kadrajdan çıkar → ASLEEP.
6. **Kapanış (20 sn):** Gizlilik (her şey lokal), rapor ekranı, gelecek planları.

> Demo'da `alert_manager` için yüksek sesli ama kısa bir alarm dosyası kullan. Salon ses sistemine bağlıysan ses seviyesini önceden ayarla.

---

## 10. Varsayımlar ve Açık Konular

| # | Konu | Durum |
|---|---|---|
| 1 | **İşletim sistemi:** Windows 11. Python **3.12** kullanılır. | **Karar verildi** |
| 2 | **Proje adı:** **NightJester**. Dosyalar proje kök klasörüne (`GDG_PAU_HACKATHON_NightJester/`) konur. Git stash mesajı `nightjester: uyku anı …`. Uygulama içindeki "Deadline modu" adı aynen kalır. | **Karar verildi** |
| 3 | **Sınıf isimlendirmesi:** Architecture.md'deki `_t` son eki yerine PEP 8 `PascalCase` seçildi. | **Karar verildi** |
| 4 | **communicator API farkı:** Çok abone desteği için `orb_subscribe` eklendi ve `orb_copy` aboneliği alıyor (ESP'de topic alıyordu). | **Karar verildi** |
| 5 | **Kod Koruyucu varsayılanı:** `enabled: true` ama `repo_paths` boş. Kullanıcı ayarlardan repo eklemeden çalışmaz. Demo için bir test reposu hazırlanmalı. | Açık |
| 6 | **Kaydedilmemiş editör içeriği:** Kod Koruyucu sadece diskteki değişiklikleri görür. VS Code'a tuş göndererek "Save All" yapmak riskli olduğu için yapılmıyor. Bunun yerine `files.autoSave = afterDelay` önerilir (kullanıcı kendisi ayarlar, sunumda da anlatılır). | **Karar verildi** |
| 7 | **Takım:** Tek kişi geliştiriyor. Fazlar sırayla uygulanır. | **Karar verildi** |
| 8 | **Skor formülü** ağırlıkları implementasyonda belirlenecek, demo ortamında ayarlanacak. | Açık |
| 9 | **Klavye/fare aktivitesi kullanılmıyor:** Kafa klavyeye düşebileceği için aktivite verisi uyku tespitinde güvenilir değil. Ayrıca geliştirme süresi kısalıyor. Aşağı bakarken oluşabilecek yanlış alarmlar kalibrasyon ve süre eşikleriyle yönetilir. | **Karar verildi** |
| 10 | **Varsayılan sesler:** `assets/sounds/alarm.wav` yerine kullanıcının hazırladığı `def_voice_files/` (kadın/erkek, Drowsy/Sleepy) kullanılır. DROWSY sesi iki modda aynıdır. Video linkleri rastgele seçilen bir listedir. | **Karar verildi** |
| 11 | **Video ile birlikte ses:** Video/link seçiliyse sadece video açılır (`deadline_sound_with_video` varsayılan `false`). Video açılamazsa yedek olarak alarm sesi çalar. | **Karar verildi** |
| 12 | **Test alarmı** sadece "Uyandım" ile (veya ASLEEP → AWAKE geçişiyle) durur. Mod Normal/Duraklat'a alınınca alarm durur. Deadline'da DROWSY sesi için cooldown yoktur. | **Karar verildi** |
| 13 | **"Kodun güvende" bildirimi:** `alert_manager` da `GUARDIAN_RESULT` dinler. Uyanışta tüm repolar başarılıysa "Hoş geldin, kodun güvende", biri başarısızsa "Kod yedeği alınamadı" bildirimi gelir. "Değişiklik yok" da başarılı sayılır (kod zaten commit'li). | **Varsayım**, onayla |
| 14 | **Kod Koruyucu bekleme süresi** (`min_interval_sec`) repo başına tutulur. Takip edilmeyen dosyalar yedeğe girmez, bu durumda log ve UI'da belirtilir. | **Varsayım**, onayla |
