# AppArmor (Application Armor)

## Определения и терминология

**AppArmor (Application Armor)** — модуль безопасности ядра Linux (LSM), реализующий систему принудительного контроля доступа (Mandatory Access Control, MAC). Разработан компанией **Canonical** и является стандартом безопасности для дистрибутивов Ubuntu, Debian и openSUSE.

В отличие от SELinux, который использует метки объектов, AppArmor ориентирован на **пути к файлам**, что делает его администрирование более интуитивно понятным.

**Ключевые особенности:**
*   **Идентификация по путям:** политики привязываются к конкретным путям в файловой системе.
*   **Избирательность:** AppArmor ограничивает только те приложения, для которых явно загружен профиль. Остальные процессы работают в режиме `unconfined` (без ограничений MAC).
*   **Минимизация поверхности атаки:** даже если злоумышленник получит права `root` через уязвимость в приложении, AppArmor запретит доступ к ресурсам, не описанным в профиле.

### История и эволюция

AppArmor прошел эволюцию от патча SuSE до стандарта де-факто в Ubuntu/Debian:

| Этап | Год | Событие |
| :--- | :--- | :--- |
| **Истоки** | 1998–2000 | Исследование Immunix (StackGuard) — патчи для ограничения приложений через `ptrace` и пути. |
| **Novell AppArmor** | 2005–2007 | Включение в SUSE Linux Enterprise 10, фокус на Usability. |
| **Canonical Adoption** | 2009+ | Ubuntu 9.10+ делает AppArmor стандартом; профили по умолчанию для cupsd, libvirt, MySQL. |
| **Docker Integration** | 2014+ | Docker применяет профиль `docker-default`; AppArmor становится частью стекка контейнерной безопасности. |
| **Kubernetes GA** | 2024–2026 | Поддержка `appArmorProfile` в SecurityContext переходит в GA (Kubernetes 1.31). |

### Ключевые термины

| Термин | Описание |
| :--- | :--- |
| **Профиль (Profile)** | Набор правил безопасности для конкретной программы. |
| **Абстракции (Abstractions)** | Переиспользуемые наборы правил (напр., доступ к сети или шрифтам), подключаемые через `#include <abstractions/...>`. |
| **Заготовки (Tunables)** | Переменные (напр., `@{HOME}`), позволяющие адаптировать профили под разные системы. |
| **LSM (Linux Security Modules)** | Фреймворк ядра, через который AppArmor перехватывает системные вызовы. |
| **SecurityFS** | Виртуальная файловая система (`/sys/kernel/security/`), через которую userspace управляет политиками AppArmor. |
| **aa-easyprof** | Утилита для генерации базовых профилей по шаблону (Python, Qt). |
| **aa-mergeprof** | Инструмент слияния двух профилей (например, ручного и сгенерированного). |

### Компоненты контекста безопасности (связь с LSM)

| Компонент | Описание | Пример |
| :--- | :--- | :--- |
| **Идентификатор приложения** | Путь к исполняемому файлу, для которого загружен профиль | `/usr/sbin/nginx` |
| **Режим профиля** | Enforce / Complain / Disabled | `enforce` |
| **Контекст файла** | AppArmor не использует расширенные атрибуты (xattrs), но может взаимодействовать с ними через маски доступа | N/A |
| **Сеть** | Правила `network inet tcp` ограничивают сокеты на уровне семейства/типа | `network inet stream,` |

## Архитектура и основные концепции

AppArmor работает как «песочница» на уровне ядра. Когда программа выполняет системный вызов (напр., `open()`), ядро проверяет, есть ли для этой программы активный профиль и разрешено ли данное действие для указанного пути.

### Интеграция в ядро (LSM Hooks + SecurityFS)

1.  **Точка входа:** При загрузке профиля через `apparmor_parser` или `systemd` ядро создает запись в SecurityFS (`/sys/kernel/security/apparmor/`) и связывает профиль с путем исполняемого файла в `securityfs` и `dentry`.
2.  **LSM Hooks:** При выполнении syscall'ов (`open`, `socket`, `ptrace` и т.д.) фреймворк LSM вызывает callback AppArmor.
3.  **Поиск профиля:** Ядро ищет профиль по `dentry` (путь к бинарнику). Если профиль найден — проверяется соответствие правила.
4.  **Действие:** В зависимости от режима (`Enforce`/`Complain`) происходит блокировка с логированием или только логирование.
5.  **No New Privileges:** В отличие от Seccomp, AppArmor не требует `no_new_privs`, но работает эффективнее в связке с ним (через `systemd`).

### Режимы работы профилей

| Режим | Описание | Применение |
| :--- | :--- | :--- |
| **Enforce** | Активное принуждение: все неразрешенные действия блокируются и записываются в лог. | Производственные среды. |
| **Complain** | Режим обучения: нарушения не блокируются, но записываются в лог как предупреждения. | Разработка и отладка профилей. |
| **Audit** | Режим расширенного логирования: записываются даже разрешенные действия (используется редко). | Глубокий аудит безопасности. |

### Структура и синтаксис профилей

Профили хранятся в `/etc/apparmor.d/`. Имя файла обычно совпадает с путем к исполняемому файлу, где `/` заменяется на `.` (например, `/usr/sbin/ntpd` → `usr.sbin.ntpd`).

```text
#include <tunables/global>

# Определение профиля для конкретного пути
/usr/bin/myapp {
  # Подключение базовых правил
  #include <abstractions/base>
  #include <abstractions/nameservice>

  # Права на файлы
  /etc/myapp/config.yaml r,        # Только чтение
  /var/log/myapp/*.log rw,        # Чтение и запись (globbing)
  /var/lib/myapp/** rwk,          # Рекурсивный доступ с блокировкой (k)

  # Сетевые правила
  network inet tcp,
  network inet stream,

  # Сигналы и ptrace
  signal (receive) set=("term", "kill") peer=unconfined,
  ptrace (trace) peer=/usr/bin/debug_tool,

  # Выполнение других программ
  /usr/bin/helper px,             # Discrete Profile: выполнить с собственным профилем
  /usr/bin/shell  ix,             # Inherit: наследовать текущий профиль
}
```

**Флаги доступа (Permissions):**
- `r` (read): чтение.
- `w` (write): запись.
- `a` (append): добавление данных в конец.
- `k` (lock): блокировка (flock/fcntl).
- `l` (link): создание жестких ссылок (hard links).
- `m` (mmap): отображение файла в память с правом исполнения (PROT_EXEC).
- `x` (execute): выполнение (обычно дополняется модификаторами `p`, `i`, `u`).

**Модификаторы выполнения (Execution modifiers):**
- `p` (Profile): discrete profile — запускается с собственным профилем AppArmor.
- `i` (Inherit): наследует профиль вызывающего процесса.
- `u` (Unconfined): запускается без профиля AppArmor (снимает ограничения).
- `x` (Disabled/Inherit): алиас для `i` в некоторых версиях.

### Сравнение с современными механизмами (2026)

| Характеристика | AppArmor | SELinux | Seccomp |
| :--- | :--- | :--- | :--- |
| **Уровень** | Пути к файлам (Средний) | Метки/контексты (Глубокий) | Номера syscall (Поверхностный) |
| **Сложность администрирования** | Низкая (пути) | Высокая (метки, роли) | Средняя (профили JSON) |
| **Привилегии** | Не требуются | Не требуются (часто) | Не требуются (no_new_privs) |
| **Инспекция указателей** | Нет | Нет | Нет |
| **Назначение** | Ограничение доступа к ФС/сети | Полный MAC на уровне ядра | Снижение поверхности атаки syscall |

## Практические сценарии

### 1. Проверка статуса и управление

```bash
# Проверка текущего состояния системы и списка профилей
sudo aa-status

# Проверка, включен ли AppArmor в ядре
sudo aa-enabled # → Yes

# Проверка режима для конкретного профиля
sudo aa-status /usr/bin/nginx
# → /usr/bin/nginx (enforced)
```

### 2. Жизненный цикл профиля: создание и обучение

**Способ A: aa-genprof (интерактивный)**

1.  **Генерация скелета:**
    ```bash
    sudo aa-genprof /usr/bin/myapp
    ```
2.  **Обучение:** пока `aa-genprof` запущен, выполняйте все стандартные действия в приложении. AppArmor перехватит обращения в режиме `Complain`.
3.  **Анализ логов:** вернитесь в терминал с `aa-genprof`, нажмите `S` (Scan). Утилита предложит правила на основе зафиксированных событий.
4.  **Сохранение:** после завершения анализа профиль будет автоматически загружен в режиме `Enforce`.

**Способ B: aa-autodep + aa-logprof (неинтерактивный)**

```bash
# Создание базового профиля
sudo aa-autodep /usr/bin/myapp

# Перевод в complain для сбора логов
sudo aa-complain /usr/bin/myapp

# Выполнение workload...
# Обновление профиля на основе логов
sudo aa-logprof
```

**Способ C: aa-easyprof (шаблоны)**

```bash
# Генерация профиля по шаблону
sudo aa-easyprof -p /usr/bin/myapp --template=network-server
```

### 3. Редактирование и валидация профилей

```bash
# После ручного редактирования профиля:
sudo apparmor_parser -r /etc/apparmor.d/usr.bin.myapp

# Проверка синтаксиса без загрузки
sudo apparmor_parser -a /etc/apparmor.d/usr.bin.myapp

# Принудительная перезагрузка всех профилей
sudo systemctl reload apparmor
```

### 4. Диагностика и устранение проблем

Если приложение падает с ошибкой `Permission Denied`, хотя права `chmod` верны:

```bash
# Просмотр отказов в реальном времени
sudo journalctl -fx | grep -i apparmor

# Просмотр через dmesg (более низкоуровневый)
sudo dmesg | grep -i apparmor

# Обновление профиля на основе накопленных логов
sudo aa-logprof
```

#### Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `apparmor="DENIED" operation="open" profile="/usr/bin/nginx"` | Профиль блокирует чтение файла | Добавить правило `путь r,` и перезагрузить профиль |
| `apparmor="DENIED" operation="bind"` | Профиль блокирует привязку к порту | Добавить правило `network inet stream,` |
| `apparmor="DENIED" operation="userns_create"` | Ubuntu 24.04+ блокирует User Namespaces | Временное отключение: `sysctl -w kernel.apparmor_restrict_unprivileged_userns=0` |
| `Permission denied` при `chmod` верен | AppArmor переопределяет DAC | Проверить `aa-status`, перевести в complain для диагностики |

#### Ubuntu 24.04+ и Unprivileged User Namespaces

В новых версиях Ubuntu (Noble Numbat) AppArmor ограничивает создание неинициализированных пространств имен пользователей. Это может блокировать работу браузеров, Docker Rootless и VPN.
*   **Диагностика:** `apparmor="DENIED" operation="userns_create"`.
*   **Решение:** создать профиль для приложения или временно отключить ограничение:
    ```bash
    sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
    ```

### 5. Режимы работы профилей

```bash
# Перевод в режим обучения
sudo aa-complain /etc/apparmor.d/usr.bin.myapp

# Возврат в режим принуждения
sudo aa-enforce /etc/apparmor.d/usr.bin.myapp

# Полное отключение профиля
sudo aa-disable /etc/apparmor.d/usr.bin.myapp

# Перевод всех профилей в complain (для массовой отладки)
sudo aa-complain /etc/apparmor.d/*
```

### 6. Профилирование через strace и audit2allow

Для создания точных профилей можно комбинировать трассировку syscall'ов с генерацией правил:

```bash
# Трассировка syscall'ов приложения
sudo strace -f -e trace=open,openat,connect,bind /usr/bin/myapp 2>&1 | grep -v EINTR | awk '{print $NF}' | sort -u

# Для AppArmor используются другие инструменты:
# aa-logprof анализирует логи AppArmor напрямую
sudo aa-logprof

# audit2allow (из пакета audit) для SELinux, но логи auditd
# содержат и события AppArmor при наличии audit subsystem
sudo ausearch -m avc -ts recent | audit2allow -M myapp
```

### 7. Ручное создание JSON-подобных профилей (CIL)

В современных дистрибутивах (Ubuntu 22.04+, Debian 12+) поддерживается CIL (Common Intermediate Language) — промежуточный язык для политик:

```text
# /etc/apparmor.d/usr.bin.myapp.cil
(profile /usr/bin/myapp /usr/bin/myapp
  (include abbrevs /usr/share/apparmor/extra-profiles/abstractions/ubuntu-baseshim)
  (allow file read)
  (allow file write)
  (allow network inet stream))
```

Компиляция:
```bash
sudo apparmor_parser -r /etc/apparmor.d/usr.bin.myapp.cil
```

### 8. systemd: интеграция с профилями AppArmor

systemd может автоматически управлять профилями AppArmor через `apparmor.service`:

```ini
# /etc/systemd/system/myapp.service
[Service]
ExecStart=/usr/bin/myapp
AppArmorProfile=/usr/bin/myapp
```

Проверка:
```bash
# Убедиться, что systemd загрузил профиль
sudo aa-status | grep myapp
# → /usr/bin/myapp (enforced)
```

### 9. Взаимодействие с User Namespaces

Внутри User Namespace процесс может иметь "полные" capabilities, но AppArmor продолжает применяться на уровне потока. Профиль ограничивает доступ к ФС и сети даже внутри user namespace.

Для Ubuntu 24.04+:
```bash
# Диагностика блокировки userns_create
sudo dmesg | grep -i "apparmor.*DENIED.*userns"

# Временное отключение ограничения (не рекомендуется в production)
sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0

# Постоянное отключение (не рекомендуется)
echo "kernel.apparmor_restrict_unprivileged_userns=0" | sudo tee -a /etc/sysctl.d/99-apparmor.conf
```

## AppArmor в контейнеризации и оркестрации

### Docker
Docker автоматически применяет профиль `docker-default` ко всем контейнерам. Он блокирует `mount`, доступ к `/proc/sysrq-trigger` и другие опасные операции.
*   **Проверка:** `docker inspect <id> --format '{{.AppArmorProfile}}'`.
*   **Свой профиль:** `docker run --security-opt apparmor=my-custom-profile alpine`.
*   **Отключение:** `docker run --security-opt apparmor=unconfined alpine`.

Подробнее: [**Укрепление безопасности контейнеров**](../../../Docker/Docker_security/container_hardening.md).

### Kubernetes (v1.30+ GA)
Начиная с версии 1.30, поддержка AppArmor в Kubernetes перешла в стадию **General Availability**. Теперь профили настраиваются непосредственно в `securityContext`.

```yaml
apiVersion: v1
kind: Pod
spec:
  securityContext:
    appArmorProfile:
      type: Localhost
      localhostProfile: my-node-profile  # Файл должен быть в /etc/apparmor.d/ на узле
  containers:
  - name: app
    image: nginx
```

Подробнее: [**Security Context в Kubernetes**](../../../Kubernetes/Security/pod_security_context.md).

### sVirt (Виртуализация)
В связке с `libvirt` и `QEMU`, AppArmor обеспечивает изоляцию виртуальных машин (технология **sVirt**). Для каждой ВМ создается динамический профиль, ограничивающий доступ только к ее собственным образам дисков.

Подробнее: [**Защита виртуализации (sVirt)**](../../Virtualization/kvm/troubleshooting.md).

### Podman
Podman использует профиль `containers-default` по умолчанию в дистрибутивах на базе Debian/Ubuntu.

```bash
# Проверка активных security-опций
podman inspect <id> --format '{{.AppArmorProfile}}'
# → containers-default
```

Подробнее: [**Изоляция в Podman**](../../../Podman/linux_isolation.md).

## Ограничения и архитектурные нюансы

1.  **Избирательность по умолчанию:** Профили применяются только к явно указанным бинарникам. Все остальные процессы работают в `unconfined`. Это удобно для развертывания, но требует внимания к путям всех исполняемых файлов.
2.  **Пути вместо меток:** AppArmor не видит содержимое файлов через hard links или renaming, если путь изменился. Для защиты от этого используйте `chmod` + `protected_hardlinks` (sysctl).
3.  **Наследование:** Профили наследуются при `execve()`, но не при `fork()` (дочерний процесс получает профиль родителя). При перезагрузке профиля все процессы автоматически получают обновленные правила.
4.  **Производительность:** Проверка происходит в LSM hooks с минимальным оверхедом (nanoseconds), но слишком широкие профили с тысячами правил `/**` замедляют `open()` syscall.
5.  **Взаимодействие с Seccomp:** AppArmor работает на уровне LSM (после проверки syscall), Seccomp — до LSM. Они дополняют друг друга, но не заменяют.

## Матрица совместимости: AppArmor и Workload

| Workload | Стандартный профиль | Требуемые исключения | Рекомендация |
| :--- | :--- | :--- | :--- |
| **Стендовый Go-сервис** | `docker-default` / `RuntimeDefault` | Нет | Стандартный профиль |
| **nginx / Apache** | `docker-default` | Доступ к `/var/log/**`, `/var/run/**` | `docker-default` + кастомный профиль |
| **PostgreSQL / MySQL** | `docker-default` | Доступ к datadir, сокетам | `docker-default` + `abstractions/mysql` |
| **Node.js / Python** | `docker-default` | Доступ к `/tmp/**`, pipes | `docker-default` + `abstractions/python` / `nodejs` |
| **SSH-сервер** | `docker-default` | `network inet stream`, `/etc/ssh/**` | Кастомный профиль |
| **Java-приложение** | `docker-default` | `memory deny mmap` (JIT), `/tmp/**` | `docker-default` + исключения JIT |
| **Системный сервис (systemd)** | Зависит от дистрибутива | `@system-service` | `SystemCallFilter` + AppArmorProfile |
| **Rootless-контейнер** | `unconfined` (часто) | Нет | `containers-default` (Podman) |
| **CI/CD раннер (untrusted)** | `docker-default` | Полный запрет `mount`, `kexec` | Кастомный строгий профиль |

### Уровни совместимости

| Обозначение | Описание |
| :--- | :--- |
| **[OK]** | Стандартный профиль работает без изменений. |
| **[!]** | Требуется добавление 1–5 путей/правил в профиль. |
| **[BLOCKED]** | Требуется критическая операция (например, `mount` хоста), которую нельзя безопасно разрешить. |

## Дополнительная информация

### Инструменты и пакеты

| Пакет | Утилиты | Назначение |
| :--- | :--- | :--- |
| `apparmor-utils` | `aa-status`, `aa-genprof`, `aa-logprof`, `aa-enforce`, `aa-complain`, `aa-disable`, `aa-autodep`, `aa-notify`, `aa-easyprof` | Управление жизненным циклом профилей |
| `apparmor` | `apparmor_parser`, `aa-mergeprof` | Парсинг, компиляция и слияние профилей |
| `auditd` | `ausearch`, `audit2allow` | Аудит и генерация правил из логов |
| `strace` | `strace`, `ltrace` | Трассировка syscall для профилирования |
| `apparmor-profiles` | (профили) | Стандартные профили для распространенных приложений |
| `apparmor-profiles-extra` | (профили) | Дополнительные профили для пакетов |
| `bpftool` | `bpftool prog list` | Инспекция BPF-программ (не для AppArmor, но для LSM-BPF) |

### Дополнительные ссылки по темам

*   **AppArmor Documentation:** [Ubuntu Wiki](https://wiki.ubuntu.com/AppArmor) — официальная документация и лучшие практики.
*   **Linux Man-pages:** [apparmor(7)](https://man7.org/linux/man-pages/man7/apparmor.7.html) — обзор модуля.
*   **libapparmor:** [GitLab](https://gitlab.com/apparmor/apparmor) — исходный код библиотеки и утилит.
*   **systemd:** [AppArmor](https://www.freedesktop.org/software/systemd/man/systemd.exec.html#AppArmorProfile=) — интеграция с юнитами.

### См. также
- [SELinux: альтернативный MAC-механизм на основе меток](./SELinux.md)
- [Обзор механизмов безопасности Linux](../Linux_Security_Mechanisms_Overview.md)
- [Seccomp: фильтрация системных вызовов](./Seccomp.md)
- [Landlock: современная песочница ФС](./Landlock.md)
- [Безопасность модулей ядра](./kernel_module_security.md) — подпись и контроль загрузки модулей
- [Безопасность подов (Pod Security Context) в Kubernetes](../../../Kubernetes/Security/pod_security_context.md)
- [Укрепление безопасности контейнеров](../../../Docker/Docker_security/container_hardening.md)
- [Изоляция в Podman](../../../Podman/linux_isolation.md)
- [Защита виртуализации (sVirt)](../../Virtualization/kvm/troubleshooting.md)
