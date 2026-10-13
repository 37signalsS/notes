# Поиск руткитов в Linux: rkhunter (Rootkit Hunter)

**Актуально для:** rkhunter 1.4.6

> **Статус:** последний официальный релиз rkhunter 1.4.6 вышел 20.02.2018; разработка фактически остановлена (версия 1.4.7 так и не была выпущена, автор проекта больше не поддерживает проект). Инструмент по-прежнему поставляется в актуальных дистрибутивах (Debian trixie — 1.4.6-13, Fedora — 1.4.6-33, EPEL 8/9/10, ALT Linux — 1.4.7-alt0_git) и получает дистрибутивные исправления, но новых сигнатур и тестов ждать не стоит. Для современных eBPF-руткитов используйте [ghostscan](./ghostscan.md).

## Определения

- **Rootkit** — набор программ, скрывающий присутствие злоумышленника в системе: маскирует процессы, файлы, сетевые соединения, перехватывает системные вызовы.
- **Rootkit Hunter (rkhunter)** — shell-скрипт для Unix-подобных систем, выполняющий набор проверок локальной системы на наличие известных руткитов, вредоносного ПО, модификаций системных команд и сетевых аномалий. Распространяется под GPLv3, официальный дом — [rkhunter.sourceforge.net](https://rkhunter.sourceforge.net).
- **File integrity checking (проверка целостности файлов)** — сравнение текущих свойств системных файлов (хеш, права, владелец, inode) с ранее сохранённым эталоном.
- **File properties database (база данных свойств файлов)** — локальный эталон rkhunter (`/var/lib/rkhunter/db/rkhunter.dat`), создаётся командой `--propupd`.
- **Signature database (база сигнатур)** — набор файлов `signatures/*.ldb` с признаками известных руткитов, обновляется командой `--update`.
- **False positive (ложное срабатывание)** — предупреждение rkhunter на легитимное изменение системы (обновление пакета, скрипт вместо бинарника, большой сегмент разделяемой памяти).

## Основные концепции

### Как работает rkhunter

rkhunter — это shell-скрипт (требует Bourne-совместимую оболочку, обычно `bash` или `ksh`), а не компилируемая программа. Он выполняет проверки последовательно, по секциям; между секциями по умолчанию запрашивает нажатия Enter (подавляется ключом `--sk`). Результат выводится на stdout и пишется в лог-файл (`/var/log/rkhunter.log` по умолчанию; при каждом запуске создаётся новый, старый переименовывается в `.old`).

Проверки организованы в пять секций (точные заголовки вывода проверены в исходном коде, файл `i18n/en`):

| Секция вывода | Что проверяет |
| :--- | :--- |
| `Checking system commands...` | проверка `strings` (сравнение выводимых строк с сигнатурами), проверка разделяемых библиотек, проверка свойств файлов (file properties check) |
| `Checking for rootkits...` | поиск известных файлов и каталогов руткитов, поиск известных строк руткитов, `Performing additional rootkit checks` (дополнительные признаки: большие сегменты разделяемой памяти, скрытые модули ядра и т. п.), проверки вредоносного ПО (`malware checks`), троянов, OS-специфичные проверки |
| `Checking the network...` | бэкдор-порты, интерфейсы в promiscuous mode |
| `Checking the local host...` | стартовые файлы, учётные записи и группы (`/etc/passwd`), системные конфигурационные файлы (SSH, syslog, скрытые файлы и каталоги, сканирование `/dev`) |
| `Checking application versions...` | версии приложений против базы `programs_bad.dat` (известные уязвимые версии) |

Полный список имён тестов (для `--enable`/`--disable`): `rkhunter --list tests`. Список искомых руткитов: `rkhunter --list rootkits`.

### Проверка целостности файлов (file properties check)

В отличие от chkrootkit, rkhunter ведёт собственную базу эталонов свойств файлов — минимальная встроенная система контроля целостности:

- Внутренний список охватывает 176 имён системных команд (`ls`, `ps`, `netstat`, `sshd`, `login` и т. п.) плюс OS-специфичные; на Linux добавляются 5 вариантов `unhide` (`unhide`, `unhide-linux`, `unhide-posix`, `unhide-tcp`, `unhide-linux26`), итого 181 имя. Фактическое число отслеживаемых файлов зависит от того, какие из них существуют в каталогах из `$PATH` (и `USER_DIR_LIST`) — на типичной Linux-системе это ~180 файлов.
- Для каждого файла сохраняются хеш и атрибуты. Хеш по умолчанию — SHA256 (ключ `--hash`; в конфиге `HASH_CMD` по умолчанию SHA1, либо MD5, если SHA1 не найден). Системы с prelink ограничены MD5/SHA1/NONE.
- Через опцию `PKGMGR` (`RPM`/`DPKG`/`BSD`/`SOLARIS`) свойства можно брать из базы пакетного менеджера.
- Эталон создаётся/обновляется командой `--propupd`. **Важно:** rkhunter умеет только констатировать факт изменения файла, но не его причину — перед `--propupd` администратор должен убедиться, что файлы подлинные, иначе изменённый руткитом файл будет принят за эталон.
- После обновления пакетов (перезаписи системных бинарников) эталон устаревает и начинает давать ложные срабатывания — `--propupd` нужно повторять.

### База сигнатур и зеркала

Сигнатуры руткитов хранятся в `/var/lib/rkhunter/db/signatures/` (в версии 1.4.6 — 16 файлов `RKH_*.ldb`: BillGates, Glubteba, MMD-0028-2014, dso, iptablex, jynx, kbeast, libkeyutils, libncom, pamunixtrojan, shv, sniffer, sshd, turtle и др.). Обновление `--update` скачивает их с зеркал из `mirrors.dat`:

- `MIRRORS_MODE` — `0` (любые зеркала, по умолчанию), `1` (только локальные), `2` (только удалённые). Локальные/удалённые зеркала задаются в `mirrors.dat` строками `local=`/`remote=`.
- `ROTATE_MIRRORS=1` (по умолчанию) — ротация списка зеркал при каждом обновлении (балансировка); `0` — зеркала как приоритетный список.
- `UPDATE_MIRRORS=1` (по умолчанию) — обновлять сам `mirrors.dat` при `--update`; для локальных зеркал обычно ставят `0`.
- `WEB_CMD` — команда для скачивания (по умолчанию не задана; rkhunter сам выбирает известную ему утилиту — `wget`, `curl`, `lynx` и т. п.). Требование: файл должен писаться в stdout, stderr игнорируется, например `WEB_CMD="/usr/bin/curl"`.

## Установка и настройка

### Установка

rkhunter есть в основных дистрибутивах; из исходников ставится через `installer.sh` (ключ `--layout` задаёт схему размещения файлов).

```bash
# Debian / Ubuntu (пакет в main)
sudo apt install rkhunter
# → result: Setting up rkhunter (1.4.6-11) ...

# RHEL / CentOS / Rocky — из EPEL
sudo dnf install epel-release
sudo dnf install rkhunter

# Fedora
sudo dnf install rkhunter

# ALT Linux
sudo apt-get install rkhunter
```

Пакет Debian/Ubuntu сразу устанавливает автоматизацию: `/etc/cron.daily/rkhunter`, `/etc/cron.weekly/rkhunter`, конфиг `/etc/default/rkhunter`, `logrotate`-правило и сниппет `/etc/apt/apt.conf.d/90rkhunter`. Пакет EPEL — `cron.daily/rkhunter`, `logrotate.d/rkhunter`, `sysconfig/rkhunter`.

### Первоначальная настройка

Конфигурация: `/etc/rkhunter.conf`. Локальные правки принято вносить не в основной файл, а в `rkhunter.conf.local` или файлы `rkhunter.d/*.conf` (в том же каталоге) — так обновления пакета не затрут настройки. Синтаксис: `ОПЦИЯ=значение`; опции со списками путей задаются по одной строке на значение (без кавычек), пробельные списки — в одну строку.

Две опции чаще всего требуют правки сразу после установки:

```bash
# /etc/rkhunter.conf.local
# Команда для скачивания обновлений (если rkhunter не нашёл подходящую сам)
WEB_CMD="/usr/bin/curl"
# Использовать любые зеркала (локальные и удалённые)
MIRRORS_MODE=0
```

Проверка корректности конфигурации (возвращает код 1 при проблемах):

```bash
sudo rkhunter --config-check
# → result: Configuration check found no errors
```

### Обновление баз и создание эталона

```bash
# 1. Обновление сигнатур и языковых файлов
sudo rkhunter --update
# → result: [ Rootkit Hunter version 1.4.6 ]
#           ... Downloading update ...
#           rkhunter update completed.

# 2. Проверка свежести версии (сравнивает установленную с последней)
sudo rkhunter --versioncheck
# → result: This version: 1.4.6  /  Latest version: 1.4.6

# 3. Создание/обновление эталона свойств файлов
sudo rkhunter --propupd
# → result: File created: searched for 181 files, found 181 files
```

Коды возврата `--update`: `0` — обновлений нет, `1` — ошибка загрузки, `2` — обновления установлены. `--versioncheck`: `0` — новая версия недоступна, `1` — ошибка загрузки, `2` — есть новая версия.

### Запуск проверки

```bash
# Полная проверка (между секциями — пауза на Enter)
sudo rkhunter --check
# или короткая форма
sudo rkhunter -c

# Без пауз (для cron и ручного запуска «в один приём»)
sudo rkhunter --check --skip-keypress
# в процессе проверки в паузе можно нажать 's' + Enter —
# остальные секции пройдут без запросов

# Только предупреждения (удобно для cron и почты)
sudo rkhunter --check --skip-keypress --report-warnings-only

# Тихий режим: никакого вывода, только код возврата
sudo rkhunter --check --skip-keypress --quiet
```

Любая ошибка или предупреждение даёт ненулевой код возврата — это основа использования rkhunter в скриптах. Лог проверки: `/var/log/rkhunter.log` (просмотр после запуска: `rkhunter --display-logfile`).

## Операции и команды

### Командная строка

| Ключ | Назначение |
| :--- | :--- |
| `-c`, `--check` | запустить проверки; лог пишется автоматически |
| `--cronjob` | как `--check`, но подразумевает `--nocolors --skip-keypress` и по умолчанию без вывода на stdout (комбинировать с `--report-warnings-only`) |
| `--update` | обновить сигнатуры/языковые файлы с зеркал |
| `--propupd [{файл \| каталог \| пакет}]` | обновить эталон свойств: целиком, либо точечно (например, `--propupd coreutils`) |
| `--versioncheck` | сравнить установленную версию с последней |
| `-C`, `--config-check` | проверить конфигурацию (все опции — `--enable all --disable none`) |
| `--list [tests \| lang \| languages \| rootkits \| perl \| propfiles]` | показать доступные тесты/языки/руткиты/модули perl/список файлов эталона |
| `--sk`, `--skip-keypress` | не останавливаться между секциями |
| `--rwo`, `--report-warnings-only` | выводить только предупреждения |
| `-q`, `--quiet` | не выводить ничего; только код возврата |
| `-l`, `--logfile [файл]` | путь к логу (по умолчанию `/var/log/rkhunter.log`); `--appendlog` — дописывать в существующий |
| `--nocolors`, `--cs2` | без цвета / вторая палитра (для белого фона); `-x`/`-X` — автоопределение X |
| `--enable`, `--disable` `<тест>[,...]` | включить/выключить конкретные тесты (`--nocf` — не учитывать `DISABLE_TESTS` из конфига) |
| `--hash {MD5\|SHA1\|SHA224\|SHA256\|SHA384\|SHA512\|NONE\|<команда>}` | хеш-функция для file properties (по умолчанию SHA256) |
| `--pkgmgr {RPM\|DPKG\|BSD\|BSDng\|SOLARIS\|NONE}` | брать свойства файлов из базы пакетного менеджера |
| `--syslog [facility.priority]` | писать время старта/финиша и предупреждения в syslog (по умолчанию `authpriv.notice`) |
| `--nomow` | не отправлять письмо при предупреждениях (перекрывает `MAIL-ON-WARNING`) |
| `--unlock` | снять lock-файл (остаётся при аварийном завершении) |
| `-V`, `--version` / `-h`, `--help` | версия / справка |

### Ключевые опции конфигурации

| Опция | Значение по умолчанию | Назначение |
| :--- | :--- | :--- |
| `ENABLE_TESTS` / `DISABLE_TESTS` | `ALL` / `NONE` | какие тесты запускать. В поставляемом конфиге отключены `suspscan hidden_ports hidden_procs deleted_files packet_cap_apps` (продвинутые/шумные) |
| `MAIL-ON-WARNING` | пусто | адреса для письма при предупреждениях; `MAIL_CMD` — команда отправки |
| `ALLOW_SSH_ROOT_USER` | `no` | сверяется с `PermitRootLogin` в `sshd_config`; значение `unset` подавляет предупреждение, если параметр не задан явно |
| `ALLOW_SSH_PROT_V1` | `0` | разрешён ли протокол SSH-1 |
| `SCRIPTWHITELIST` | пусто | разрешить файлу быть скриптом (по одной строке на путь, wildcards разрешены) |
| `USER_FILEPROP_FILES_DIRS` / `EXCLUDE_USER_FILEPROP_FILES_DIRS` | пусто | добавить/исключить пути в проверке свойств (wildcards разрешены) |
| `ALLOWHIDDENDIR` / `ALLOWHIDDENFILE` | пусто | белый список скрытых каталогов/файлов (wildcards разрешены) |
| `ALLOWPROMISCIF` | пусто | интерфейсы, которым разрешён promiscuous mode |
| `ALLOWPROCLISTEN` | пусто | процессы, которым разрешено слушать на любом интерфейсе |
| `ALLOWDEVFILE` | пусто | разрешённые файлы в `/dev`; `SCAN_MODE_DEV=THOROUGH` — глубокое сканирование `/dev` |
| `PORT_WHITELIST` / `PORT_PATH_WHITELIST` | пусто | белый список портов (`TCP:2001`) и исполняемых файлов (требуется `lsof`) |
| `RTKT_FILE_WHITELIST` / `RTKT_DIR_WHITELIST` | пусто | белый список файлов/каталогов для проверок руткитов и вредоносного ПО |
| `EXISTWHITELIST` | пусто | файлы/каталоги, чьё наличие или отсутствие не считать подозрительным |
| `TMPDIR` / `DBDIR` / `SCRIPTDIR` | `/var/lib/rkhunter/tmp` / `/var/lib/rkhunter/db` / каталог скриптов | рабочие каталоги (не использовать `/tmp` для `TMPDIR`) |
| `USE_LOCKING` / `LOCK_TIMEOUT` | `0` / `300` | блокировка параллельных запусков |
| `SCANROOTKITMODE=THOROUGH` | пусто | искать файлы руткитов по всей ФС (`find / -xdev`) — только для расследований, не по умолчанию |
| `SUSPSCAN_DIRS` / `SUSPSCAN_MAXSIZE` / `SUSPSCAN_THRESH` | `/tmp /var/tmp` / `1024000` / `200` | параметры теста `suspscan` (CPU/I/O-интенсивный, по умолчанию отключён) |

## Устранение неполадок

### Ложные срабатывания на скриптах вместо бинарников

Симптом в секции `Checking system commands...`: «Warning: The command ... is a script, not a binary». Часть утилит в дистрибутивах изначально являются скриптами (например, `/usr/bin/groups`, `/usr/bin/ldd`, `/sbin/ifup`). Решение — белый список:

```bash
# /etc/rkhunter.conf.local
SCRIPTWHITELIST=/usr/bin/groups
SCRIPTWHITELIST=/usr/bin/ldd
```

### Ложное срабатывание на большом сегменте разделяемой памяти

В секции дополнительных проверок руткитов rkhunter проверяет System V shared memory (только Linux): сегмент с правами `666` и размером >= 1 000 000 байт (~1 МБ) считается подозрительным. **Порог захардкожен в исходном коде (`malware_checks()`), опции конфигурации для его изменения нет** — увеличить лимит, как иногда советуют, невозможно. На десктопах (браузеры, медиаплееры) и на серверах (СУБД, использующие большие SHM-сегменты) это регулярный false positive. Варианты: принять предупреждение как известный шум, либо отключить тест целиком (`DISABLE_TESTS=malware` — нежелательно, отключает все проверки вредоносного ПО).

### Несоответствие конфигурации SSH

Предупреждение о `PermitRootLogin`: сверите значение в `/etc/ssh/sshd_config` с `ALLOW_SSH_ROOT_USER` (`no`/`yes`/`unset`). Если параметр в `sshd_config` не задан явно, поставьте `ALLOW_SSH_ROOT_USER=unset`.

### Скрытые файлы и каталоги

Предупреждения «Warning: Hidden file found» / «Hidden directory found» — например, man-страницы конфигурационных файлов, имена которых начинаются с точки (`/usr/share/man/man1/..1.gz`), или служебные каталоги (`/dev/.udev`). Добавляются в белый список:

```bash
# /etc/rkhunter.conf.local
ALLOWHIDDENFILE=/usr/share/man/man1/..1.gz
ALLOWHIDDENDIR=/dev/.udev
```

### Ошибки обновления

`--update` не может скачать данные: проверьте `WEB_CMD` (утилита должна писать в stdout) и `MIRRORS_MODE`; при использовании только локальных зеркал поставьте `UPDATE_MIRRORS=0`. Требуется одна из утилит: `wget`, `curl`, `(e)links`, `lynx`.

### Остались предупреждения после настройки

Повторите `rkhunter --config-check`, затем `sudo rkhunter --propupd` (после любых изменений опций, влияющих на свойства файлов: `HASH_CMD`, `PKGMGR`, `USER_FILEPROP_FILES_DIRS` и др.), и запустите проверку снова. Для отладки конкретного предупреждения полезно `--verbose-logging` (включён по умолчанию) и просмотр `/var/log/rkhunter.log`.

## Лучшие практики

- **Регулярность:** обновление сигнатур и эталона — раз в неделю, проверки — раз в день. Пакет Debian/Ubuntu уже содержит `/etc/cron.daily/rkhunter` и `/etc/cron.weekly/rkhunter`; управление — через `/etc/default/rkhunter` (`CRON_DAILY_RUN=yes`, `CRON_DB_UPDATE=yes`, `REPORT_EMAIL=admin@example.com`, `NICE`, `RUN_CHECK_ON_BATTERY=false`). Cron-скрипт использует `rkhunter --cronjob --report-warnings-only --appendlog` и шлёт письмо только при наличии предупреждений.
- **Эталон после изменений:** запускайте `--propupd` после обновления системы/пакетов — иначе каждое обновление бинарников даст ложные срабатывания.
- **Расследуйте каждое предупреждение:** rkhunter констатирует факт изменения, но не его причину. Не добавляйте в белые списки и не делайте `--propupd` на «чтобы не ругался» — сначала проверьте файл (`rpm -V`/`debsums`, пакетный менеджер, хеш с эталона с доверенного носителя).
- **Защита самого эталона:** база `/var/lib/rkhunter/db/` writable для root — при компрометации злоумышленник может обновить эталон. Для высоконадёжных сценариев храните эталон на read-only носителе или отправляйте хеш базы в SIEM; для полноценного FIM используйте [AIDE/Tripwire](../../Linux/Security/Concepts/file-integrity-checking.md).
- **Комбинируйте инструменты:** rkhunter — сигнатурный сканер с проверкой свойств файлов; в конфигурации по умолчанию не проверяет скрытые процессы (тест `hidden_procs` отключён в поставляемом конфиге — для этой задачи используйте `chkproc` из [chkrootkit](./chkrootkit.md)); он не видит современные eBPF-руткиты (см. [ghostscan](./ghostscan.md)) и не заменяет мониторинг ядра ([Wazuh](./wazuh.md), [Falco](./falco.md)). В рамках реагирования на инциденты rkhunter — один из первых скринингов ([incident response](../../Linux/Security/Concepts/incident_response.md)).
- **Очистка:** удаление — `sudo apt remove rkhunter` (или `dnf remove rkhunter`); cron-скрипты и `/var/log/rkhunter.log` удаляются вместе с пакетом.

## Дополнительная информация

- Официальный сайт и документация: [rkhunter.sourceforge.net](https://rkhunter.sourceforge.net); man-страницы: `man rkhunter`, `man 5 rkhunter.conf` (онлайн: [rkhunter.8](https://man.archlinux.org/man/rkhunter.8.txt)).
- Исходный код: [SourceForge git](https://sourceforge.net/p/rkhunter/rkh_code/ci/master/tree/).
- Сравнение с chkrootkit: chkrootkit не имеет конфигурационного файла (всё задаётся параметрами командной строки) и не ведёт базу свойств файлов; rkhunter — наоборот, конфигурируется через `/etc/rkhunter.conf` и отслеживает ~180 системных команд. Оба инструмента сигнатурные и дополняют, а не заменяют друг друга; на примере LKM-руткита Diamorphine разница в детекции показана в [chkrootkit](./chkrootkit.md).
- Связанные файлы базы знаний: [ghostscan](./ghostscan.md) (eBPF-руткиты), [Wazuh](./wazuh.md) и [Falco](./falco.md) (мониторинг в реальном времени), [Проверка целостности файлов](../../Linux/Security/Concepts/file-integrity-checking.md) (AIDE, Tripwire, IMA/EVM), [Реагирование на инциденты](../../Linux/Security/Concepts/incident_response.md).
