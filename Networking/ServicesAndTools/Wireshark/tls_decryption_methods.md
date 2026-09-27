# Методы расшифровки TLS-трафика

> **SSoT:** Определения базовых терминов (SSLKEYLOGFILE, DSB, PQC, QUIC, Wireshark) — в **[Определения](./definitions.md)** и в этом файле (TLS-специфичные). Концепции захвата — в **[Основные концепции](./core_concepts.md)**. Практические сценарии расшифровки — в **[Практические сценарии](./practical_scenarios.md)**. Автоматизация в CLI — в **[Использование tshark](./tshark_usage.md)**.

## Определения

**Расшифровка TLS (Transport Layer Security)** — процесс получения доступа к содержимому защищенного соединения с использованием ключей сессии или промежуточных секретов, полученных на этапе установления связи (handshake).

**SSLKEYLOGFILE** — стандартный текстовый формат файла для записи TLS-ключей. Поддерживается браузерами (Chrome, Firefox), приложениями на базе Electron и инструментами перехвата (Mitmproxy).

**TLS Keylog Launcher** — встроенный инструмент Wireshark (4.2+), автоматизирующий запуск браузеров с предустановленными переменными окружения для экспорта ключей.

**ECH (Encrypted Client Hello)** — расширение TLS 1.3, шифрующее начальный пакет `ClientHello` (включая SNI). Для расшифровки в Wireshark требуются специфические секреты или конфигурация ECH-ключей.

**PQC (Post-Quantum Cryptography)** — алгоритмы шифрования, устойчивые к атакам квантовых компьютеров. В 2026 году TLS 1.3 активно использует гибридные группы (например, X25519 + ML-KEM), которые Wireshark поддерживает при наличии сессионных секретов.

**Decryption Secrets Block (DSB)** — специальный блок в формате файла `pcapng` (начиная с Wireshark 3.0), позволяющий встраивать секреты расшифровки (TLS ключи) непосредственно в дамп трафика. Это избавляет от необходимости передавать отдельный файл ключей.

**QUIC (HTTP/3) Decryption** — процесс расшифровки трафика на базе протокола UDP. В отличие от TCP TLS, QUIC шифрует почти все поля заголовков, требуя ключи для любого уровня анализа.

**PFS (Perfect Forward Secrecy)** — свойство шифрования, гарантирующее, что компрометация долгосрочного ключа сервера не позволит расшифровать прошлые сессии. Требует обязательного захвата сессионных ключей в реальном времени.

**DTLS (Datagram TLS)** — версия TLS для UDP, используемая в WebRTC, VPN (OpenVPN) и VoIP. Расшифровка аналогична TLS, но требует указания протокола в настройках Wireshark (`Preferences → Protocols → DTLS`).

## Основные концепции

### Какую методику расшифровки выбрать?

```
Поддерживает ли приложение SSLKEYLOGFILE?
├── ДА → Используйте SSLKEYLOGFILE (самый простой способ)
│         ├── Браузер → TLS Keylog Launcher (Wireshark 4.2+)
│         ├── Electron → export SSLKEYLOGFILE=...
│         └── Go/Python → см. сценарий eBPF
└── НЕТ
    ├── Есть доступ к CA-ключам сервера?
    │   ├── ДА → RSA-расшифровка (tls.key_list) — только TLS 1.2
    │   └── НЕТ → MITM-прокси (mitmproxy/Charles/Fiddler)
    ├── Это DTLS (WebRTC/VPN)?
    │   └── Да → Указать DTLS в настройках протокола
    └── Это Kubernetes/Service Mesh?
        └── eBPF-пробы (DeepFlow, Inspektor Gadget)
```

### Различия между TLS 1.2 и TLS 1.3

Процесс расшифровки существенно зависит от версии протокола. Подробный разбор механики — в разделе **[Протокол TLS](../../Protocols/tls.md)**.

| Аспект | TLS 1.2 | TLS 1.3 |
| :--- | :--- | :--- |
| **Алгоритмы обмена** | RSA и (EC)DHE | Только (EC)DHE (PFS по умолчанию) |
| **Расшифровка ключом сервера** | Возможна для RSA-шифров | Невозможна (RSA удален) |
| **Формат логов ключей** | Одна запись `CLIENT_RANDOM` | Множество записей для разных фаз сессии |
| **Шифрование Handshake** | Частично открытый | Почти полностью зашифрован (требует HS-секреты) |
| **Приватность метаданных** | SNI передается открыто | SNI может быть скрыт через ECH |

### Расшифровка QUIC (HTTP/3)

Wireshark (начиная с v3.4+) поддерживает расшифровку QUIC через тот же механизм `SSLKEYLOGFILE`. Основные нюансы:
- **UDP-порт:** По умолчанию QUIC работает на 443/UDP. Если порт нестандартный, его нужно указать в настройках: `Preferences → Protocols → QUIC`.
- **Версии:** Поддержка RFC 9000 и современных черновиков (drafts).
- **eBPF-перехват:** Для приложений, использующих `quictls` или `ngtcp2`, классические перехватчики OpenSSL могут не сработать. Требуются специализированные eBPF-пробы (например, из состава DeepFlow или Inspektor Gadget).

```bash
# tshark: расшифровка QUIC с указанием порта
tshark -r quic_traffic.pcapng -o tls.keylog_file:~/tls-keys.log -o "quic.udp.port:443" -Y "http3"

# Wireshark GUI: Preferences → Protocols → QUIC → UDP Port(s) = 443
```

### Encrypted Client Hello (ECH) и Post-Quantum (PQC)

В 2026 году эти технологии стали стандартом:
1.  **ECH:** Если клиент использует ECH, Wireshark не сможет увидеть доменное имя (SNI) без расшифровки "Inner ClientHello". Для этого в настройках TLS (`Preferences → Protocols → TLS`) необходимо указать файл с ECH-ключами (Private Keys), если они доступны.
2.  **PQC:** При использовании гибридных квантово-устойчивых схем (например, X25519MLKEM768) объем `Key Share` в пакете увеличивается. Wireshark 4.4+ автоматически обрабатывает эти алгоритмы, если в `SSLKEYLOGFILE` предоставлены корректные секреты.

```bash
# tshark: фильтрация PQC handshake
tshark -r tls13.pcapng -Y "tls.handshake.type == 1 && tls.handshake.extensions.supported_group" -T fields -e tls.handshake.extensions.supported_group
```

### Внедрение ключей в pcapng (DSB)

Современный стандарт SRE — хранение ключей внутри дампа:
1. Wireshark автоматически сохраняет ключи в `pcapng`, если они были доступны при записи.
2. **Экстракция секретов:** С помощью утилиты `editcap` (входит в Wireshark) можно извлечь внедренные ключи:
   ```bash
   editcap --extract-secrets capture.pcapng secrets.txt
   ```
3. Это критично при передаче дампов между командами для соблюдения безопасности (ключи передаются только для конкретного дампа).

```bash
# Внедрение ключей в pcapng через tshark
tshark -r input.pcap -o tls.keylog_file:~/tls-keys.log -w output.pcapng

# Проверка наличия DSB в pcapng
tshark -r capture.pcapng -q -z io,phs | head -5
```

### Расшифровка через CA-сертификат (RSA-only, TLS 1.2)

Для серверов с RSA-шифрованием (без PFS) можно расшифровать трафик, имея приватный ключ сервера:
```bash
# tshark: расшифровка через приватный ключ сервера
tshark -r capture.pcap -o tls.keys_list:192.168.1.100,443,http,/etc/ssl/private/server.key

# Формат: IP,PORT,PROTOCOL,PATH_TO_KEY
# Только для TLS 1.2 с RSA! TLS 1.3 не поддерживает этот метод.
```

> **Важно:** RSA-расшифровка работает только для TLS 1.2 без PFS. В TLS 1.3 RSA-ключ не используется для шифрования сессионных ключей.

## Практические сценарии

### Сценарий 1: TLS Keylog Launcher (Wireshark 4.2+)

Самый простой способ для отладки трафика браузера в 2026 году:
1.  Откройте **Tools → TLS Keylog Launcher**.
2.  Укажите путь к лог-файлу (например, `/tmp/tls-keys.log`) и путь к исполняемому файлу браузера.
3.  Нажмите **Launch**. Wireshark запустит браузер с уже настроенным экспортом.
4.  В настройках Wireshark (`Edit → Preferences → Protocols → TLS`) укажите этот же файл в поле **(Pre)-Master-Secret log filename**.
5.  Трафик будет расшифровываться на лету (появится вкладка **Decrypted TLS**).

```bash
# Альтернатива: запуск из командной строки
export SSLKEYLOGFILE=~/tls-keys.log
google-chrome --user-data-dir=/tmp/debug
# Или Firefox:
# export SSLKEYLOGFILE=~/tls-keys.log
# firefox -profile /tmp/debug-profile
```

> **Важно:** После настройки `SSLKEYLOGFILE` в Wireshark также включите:
> - `Edit → Preferences → Protocols → TCP → Allow subdissector to reassemble TCP streams`
> - Вторая опция TCP (переупорядочивание сегментов, указанная в документации Wireshark).
> Без этих параметров TLS-сессии могут не расшифровываться корректно.

### Сценарий 2: Использование eBPF для "Zero-Instrumentation" (Linux)

Для приложений без поддержки `SSLKEYLOGFILE` (Go-бинарники, старое ПО, AI-агенты):
1.  **DeepFlow / Inspektor Gadget:** Используйте eBPF-пробы (uprobes) для перехвата данных в памяти процесса до шифрования.
    ```bash
    # Пример с Inspektor Gadget
    ig trace ssl --containername my-app
    ```
2.  **eCapture:** Утилита для захвата HTTPS без необходимости в CA-сертификатах. Поддерживает OpenSSL, BoringSSL, GnuTLS.
3.  **Преимущество:** eBPF позволяет видеть plaintext даже при использовании статически скомпилированных библиотек шифрования (через паттерн-матчинг инструкций в 2026 году).

```bash
# eCapture: захват TLS-секретов через eBPF
sudo ecapture tls --hexmask=false

# Inspektor Gadget: захват в Kubernetes
kubectl gadget trace ssl -n <namespace> -c <container>
```

### Сценарий 3: Расшифровка в Kubernetes и Service Mesh

1.  **Ksniff:** Плагин `kubectl sniff` для захвата трафика пода. Если под имеет права `CAP_BPF`, можно прокидывать ключи напрямую.
2.  **Service Mesh (Istio/Linkerd):** Трафик mTLS между прокси (Envoy) можно расшифровать, если настроить Envoy на экспорт секретов через `metadata_log` или использовать eBPF-агенты (DeepFlow), которые автоматически коррелируют трафик с процессами.
3.  **Sidecar Decryption:** Внедрение прокси, который терминирует TLS и передает plaintext приложению через `localhost`, что упрощает захват на петлевом интерфейсе (`lo`).

```bash
# Захват с SSLKEYLOGFILE через ephemeral container
kubectl debug -it <pod> --image=nicolaka/netshoot -- \
  env SSLKEYLOGFILE=/tmp/keys.log <app-command>

# Извлечение ключей из пода
kubectl exec <pod> -- cat /tmp/keys.log > ~/pod-keys.log
tshark -r <pod-capture.pcapng> -o tls.keylog_file:~/pod-keys.log
```

### Сценарий 4: Mobile & IoT (Frida + eCapture)

1.  **SSL Pinning Bypass:** Используйте **Frida** для отключения проверки сертификатов.
2.  **eCapture (Android):** В 2026 году eCapture является стандартом для Android (ARM64), позволяя захватывать трафик BoringSSL без модификации APK.
3.  **Mitmproxy:** Перенаправьте трафик на прокси с включенным логированием:
    ```bash
    mitmproxy --set sslkeylogfile=~/tls-keys.log
    ```

```bash
# Frida: bypass SSL pinning (Android)
frida -U -f com.example.app -l ssl_pinning_bypass.js

# Frida: bypass SSL pinning (iOS)
frida -U -f com.example.app -l ssl_pinning_bypass_ios.js
```

### Сценарий 5: MITM-прокси для приложений без SSLKEYLOGFILE

Для приложений, которые не поддерживают SSLKEYLOGFILE и eBPF недоступен:
```bash
# mitmproxy: перехват + экспорт ключей
mitmproxy --set sslkeylogfile=~/tls-keys.log -p 8080

# Charles Proxy: включить SSL Proxying для нужных доменов
# Proxy → SSL Proxying Settings → Add: *.example.com:443

#mitmproxy: автоматическая генерация CA-сертификата
mitmproxy --set ssl_insecure=true -p 8080
```

**Настройка устройства:**
1. Установите CA-сертификат прокси на устройство
2. Настройте прокси на устройстве (IP: 8080)
3. Для iOS/Android 7+: установите CA в system certificate store (требуется root или jailbreak)

### Сценарий 6: Расшифровка DTLS (WebRTC/VPN)

```bash
# tshark: DTLS-расшифровка
tshark -r webrtc.pcapng -o tls.keylog_file:~/dtls-keys.log -Y "dtls"

# Wireshark: настройка DTLS
# Preferences → Protocols → DTLS → Port(s) = 443 (или другой порт)

# Фильтрация RTP после DTLS-расшифровки
tshark -r webrtc.pcapng -o tls.keylog_file:~/dtls-keys.log -Y "rtp" -T fields -e rtp.ssrc -e rtp.seq -e rtp.timestamp
```

### Сценарий 7: Windows — ручная настройка SSLKEYLOGFILE

На Windows переменная окружения `SSLKEYLOGFILE` создаётся через системные настройки:

1. Откройте **Мой компьютер** → **Свойства** → **Дополнительные параметры системы** → **Переменные среды**.
2. Нажмите **Создать** в разделе «Переменные среды пользователя».
3. В поле **Имя переменной** введите `SSLKEYLOGFILE`.
4. В поле **Значение переменной** укажите полный путь к файлу, например `C:\Users\<user>\tls-keys.log`.
   - Если файл не существует, он будет создан автоматически при первом экспорте ключей.
5. Нажмите **ОК** во всех окнах и **перезапустите браузер**.

> **Важно:** Браузер, запущенный до создания переменной окружения, не увидит её. В некоторых случаях требуется перезагрузка компьютера.

**Проверка:**
После перезапуска откройте HTTPS-сайт и убедитесь, что в файл записываются ключи:
```powershell
# Просмотр последних записей в файле ключей
Get-Content C:\Users\<user>\tls-keys.log -Tail 5
```

В логе появляются записи, соответствующие phases сессии:
- `CLIENT_HANDSHAKE_TRAFFIC_SECRET` — секреты этапа Handshake
- `CLIENT_TRAFFIC_SECRET_0` — данные от клиента к серверу
- `SERVER_TRAFFIC_SECRET_0` — данные от сервера к клиенту
- `CLIENT_RANDOM` — формат TLS 1.2 (RSA)

## Дополнительная информация

### Формат файла логов (NSS Key Log)

| Лейбл | Назначение (2026) |
| :--- | :--- |
| `CLIENT_HANDSHAKE_TRAFFIC_SECRET` | Расшифровка этапа Handshake (Encrypted Extensions). |
| `CLIENT_TRAFFIC_SECRET_0` | Данные от клиента к серверу (первая фаза). |
| `SERVER_TRAFFIC_SECRET_0` | Данные от сервера к клиенту (первая фаза). |
| `CLIENT_EARLY_TRAFFIC_SECRET` | Расшифровка 0-RTT данных (Early Data). |
| `EXPORTER_SECRET` | Для ключей, производных от TLS-экспортера. |
| `ECH_OUTER_CLIENT_HELLO` | Секреты для расшифровки внешнего ECH-заголовка. |
| `CLIENT_RANDOM` | Формат TLS 1.2 (RSA). |

> **Примечание по ротации ключей:** В долгоживущих сессиях (например, gRPC-стримы) ключи могут обновляться. В логах появятся записи `CLIENT_TRAFFIC_SECRET_1`, `_2` и т.д. Убедитесь, что ваш инструмент сбора логов поддерживает захват этих событий.

### Типичные ошибки при расшифровке

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `TLS, Application Data` в Packet Details | Нет ключей или неправильный файл | Проверить путь к SSLKEYLOGFILE |
| `Decrypted TLS` не появляется | Ключи не совпадают с сессией | Перезапустить браузер с SSLKEYLOGFILE |
| QUIC не расшифровывается | Порт нестандартный | Настроить порт в `Preferences → Protocols → QUIC` |
| `No decryption keys available` | PQC-схема не поддерживается | Обновить Wireshark до 4.4+ |
| `ECH: can't decrypt Inner CH` | Нет ECH-ключей | Указать ECH Private Keys в TLS-настройках |
| RSA-расшифровка не работает | TLS 1.3 (RSA удален) | Использовать SSLKEYLOGFILE вместо RSA-ключа |
| `Follow Stream` показывает мусор | Трафик зашифрован | Расшифровать через SSLKEYLOGFILE или MITM |
| DTLS не расшифровывается | Протокол не указан | Включить DTLS в настройках протокола |
| Трафик не найден по IP на shared hosting | У домена несколько A/AAAA-записей | Переберите все IP-адреса или используйте фильтр по SNI (`tls.handshake.extensions_server_name == "domain"`) |

### Сравнение методов расшифровки

| Метод | TLS 1.2 | TLS 1.3 | QUIC | DTLS | Сложность |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **SSLKEYLOGFILE** | Да | Да | Да | Да | Низкая |
| **RSA-ключ сервера** | Да (без PFS) | Нет | Нет | Да | Средняя |
| **MITM-прокси** | Да | Да | Ограниченно | Да | Высокая |
| **eBPF (eCapture)** | Да | Да | Да | Да | Высокая |
| **DSB (в pcapng)** | Да | Да | Да | Да | Низкая |

### См. также

- **[Протокол TLS](../../Protocols/tls.md)** — теоретические основы шифрования и хендшейка.
- **[Определения Wireshark](./definitions.md)** — обзор инструментов и форматов данных.
- **[tshark — расшифровка в CLI](./tshark_usage.md)** — использование ключей в консольном анализаторе.
- **[Практические сценарии Wireshark](./practical_scenarios.md)** — общие кейсы диагностики.
- **[Основные концепции захвата](./core_concepts.md)** — NIC ring buffer, offloading, multi-iface захват.
- **[Service Mesh](./service_mesh_analysis.md)** — расшифровка mTLS в Istio/Envoy.
- **[HTTP/2 и gRPC](./http2_grpc_analysis.md)** — анализ HTTP/2 (включая зашифрованный).
- **[eBPF-инструменты](./ebpf_diagnostics_tools.md)** — eBPF для захвата ключей (DeepFlow, eCapture).
