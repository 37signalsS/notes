# Linux Capabilities

## Определения

**Linux Capabilities** — это механизм ядра Linux, который разделяет монолитные привилегии суперпользователя (`root`, UID 0) на гранулярные, атомарные единицы доступа (примерно 40+ независимых категорий). В традиционной модели безопасности Unix процессы делятся на две категории:
1.  **Непривилегированные** (UID != 0): подвергаются строгой проверке прав доступа (DAC).
2.  **Привилегированные** (UID == 0): обходят все проверки безопасности ядра.

Capabilities реализуют **принцип наименьших привилегий**, позволяя назначать процессу только специфические права, необходимые для выполнения задачи (например, только право занимать порт 80). Это минимизирует риски: компрометация процесса с одной привилегией не дает злоумышленнику полного контроля над системой.

Механизм служит фундаментом для современных систем изоляции, таких как Docker, Kubernetes и rootless-контейнеры.

### История и эволюция

В ранней модели Unix у процесса были только учётные данные (UID, GID): когда процесс обращался к файлу, отправлял сигнал или просил ядро о другой операции, ядро сверяло эти данные. Процессы с UID 0 стояли особняком — они обходили все проверки ядра, тогда как пользовательские процессы проходили их полностью. Проблема: программе часто была нужна ровно одна привилегированная операция (открыть порт < 1024, сменить владельца файла, настроить сетевой интерфейс), но отдельного разрешения на такую операцию в классической модели не существовало — весь процесс приходилось запускать от root. В результате программа с одной привилегированной операцией получала почти все права в системе, а найденная в ней уязвимость отдавала тот же набор атакующему.

Поэтому в 1999 году, начиная с ядра Linux 2.2, монолитные полномочия root разделили на отдельные возможности — capabilities (несколько десятков; полный список — `man 7 capabilities`). Примеры: `CAP_NET_BIND_SERVICE` — слушать привилегированные порты, `CAP_CHOWN` — менять владельца файлов, `CAP_NET_ADMIN` — управлять сетевыми настройками, `CAP_SYS_PTRACE` — операции над другими процессами через ptrace.

### Итерации и современное состояние (1999–2026)

*   **Linux 2.2 (1999):** Введение базового набора capabilities (~27). Файловые возможности ещё не поддерживались.
*   **Linux 2.4 (2001):** Добавлены `CAP_SETPCAP` и `CAP_AUDIT_WRITE`. Появилась возможность передавать capabilities через `execve()`.
*   **Linux 2.6.24 (2008):** Добавлен набор `Ambient` (как `AT_SECURE`-совместимый механизм передачи прав). Начало поддержки файловых возможностей в VFS.
*   **Linux 3.2 (2012):** Стабилизация файловых возможностей V2. Docker начинает использовать capabilities для контейнерной изоляции.
*   **Linux 4.14 (2017):** Добавлены `CAP_BPF` и `CAP_PERFMON` как альтернативы `CAP_SYS_ADMIN` для eBPF. Ужесточение контроля над `CAP_SYS_ADMIN` в контейнерах.
*   **Linux 5.1 (2019):** Введение `CAP_CHECKPOINT_RESTORE` для CRIU. Упрощение миграции контейнеров без полного root.
*   **Linux 5.8 (2020):** Добавлены capabilities для контроля доступа к memory protection keys (`CAP_MPKS`).
*   **Linux 6.1 (2022):** Доработка взаимодействия с User Namespaces. `CAP_SYS_ADMIN` внутри user namespace уже не даёт доступа к хосту.
*   **Linux 6.8 (2024):** Расширение набора `Ambient` для нетипичных сценариев (init-системы, язык Go).
*   **Linux 6.12 (2025):** Оптимизация проверок capabilities в hot-path ядра (снижение накладных расходов при большом количестве потоков).
*   **Текущий стандарт (2026):** Полный набор — 40+ возможностей. Стандарт де-факто для hardening: `drop ALL` + явный `add` только необходимых.

## Основные концепции

### Наборы возможностей (Capability Sets)

Ядро отслеживает пять наборов capabilities для каждого процесса (потока):

*   **`Permitted` (Разрешенные):** Жесткий предел возможностей, которые процесс может использовать или перевести в эффективный набор.
*   **`Effective` (Эффективные):** Набор прав, которые ядро фактически проверяет в данный момент при выполнении системных вызовов.
*   **`Inheritable` (Наследуемые):** Возможности, которые могут быть переданы через вызов `execve()`. В современной практике часто заменяются на `Ambient`.
*   **`Bounding` (Ограничивающий):** Фильтр, ограничивающий максимальные возможности, которые процесс может получить (даже через SUID-файлы).
*   **`Ambient` (Окружающие):** Позволяют непривилегированным процессам передавать свои возможности дочерним процессам при `execve()`. Это критично для запуска скриптов и бинарных файлов (например, на Go), которые не могут иметь установленных файловых возможностей.

### Привязка к процессу: структура cred

Capabilities — не отдельная фича Docker или другой userspace-программы, а обычные полномочия Linux-процесса. В ядре они хранятся не прямо в `task_struct`, а в отдельной структуре `cred` (credentials), на которую `task_struct` каждого потока ссылается. Рядом с capability sets в `cred` лежат UID/GID процесса: современная модель выглядит не как «UID 0 — можно всё», а как единый набор credentials (идентификаторы пользователя + набор capabilities), который ядро проверяет при выполнении привилегированных операций.

Нюансы:
*   Строго говоря, capability относится к потоку (thread), но на практике говорят «у процесса».
*   Capabilities работают не только для root: процесс с UID 1337 может иметь, например, `CAP_NET_BIND_SERVICE` и слушать порты < 1024 без запуска всего приложения от root.
*   Одинаковый UID ещё не означает одинаковые полномочия — наборы capabilities двух процессов могут отличаться (см. сценарий диагностики ниже).
*   Capability имеет смысл относительно конкретного user namespace: `CAP_SYS_ADMIN` внутри отдельного user namespace не обязательно даёт те же полномочия, что и в initial user namespace хоста (подробнее — в разделе о User Namespaces ниже).

### Файловые возможности (File Capabilities)

Возможности могут быть записаны в расширенные атрибуты файла (`security.capability`). При запуске такого файла ядро объединяет его возможности с возможностями процесса.

**Версии VFS-атрибутов (2025–2026):**
*   **V2:** Классическая версия.
*   **V3 (Namespaced):** Стандарт для контейнеров. Включает в себя ID пространства имен пользователя (User Namespace Root UID), для которого эти права валидны. Это предотвращает использование привилегий за пределами целевого контейнера.

### Взаимодействие с no_new_privs

Флаг `no_new_privs` (NNP) гарантирует, что процесс никогда не получит новых прав через `execve()`.
*   При включенном NNP ядро игнорирует SUID-биты и файловые возможности (`fcaps`).
*   **Исключение:** Набор `Ambient` продолжает работать даже при NNP, что делает его предпочтительным методом передачи прав в защищенных средах.

### Ключевые термины

| Термин | Описание |
| :--- | :--- |
| **Capability** | Атомарное право ядра Linux (например, `CAP_NET_BIND_SERVICE`). |
| **Capability Sets** | Пять наборов, привязанных к процессу: Permitted, Effective, Inheritable, Bounding, Ambient. |
| **File Capabilities** | Расширенные атрибуты файла (`security.capability`), задающие capabilities, которые ядро добавит при `execve()`. |
| **no_new_privs (NNP)** | Флаг процесса, запрещающий получение новых прав через `execve()` (SUID, fcaps). |
| **Ambient** | Набор capabilities, наследуемый дочерними процессами через `execve()` без файловых возможностей. |
| **Bounding Set** | Жёсткий фильтр максимальных capabilities, доступных процессу. |
| **cred** | Структура ядра, хранящая UID/GID и capability sets процесса (не в `task_struct` напрямую). |
| **VFS capability version** | Версия формата атрибута `security.capability` (V2, V3 Namespaced). |
| **CAP_SYS_ADMIN** | Capability с наибольшим числом прав; часто называется «универсальным ключом». |

### Сравнение с современными механизмами (2026)

| Механизм | Уровень | Что контролирует | Привилегии для настройки | Область применения |
| :--- | :--- | :--- | :--- | :--- |
| **DAC (rwx)** | Файлы/процессы | Владелец, группа, остальные | Не требуются | Базовая изоляция |
| **Capabilities** | Процесс (UID 0) | Гранулярные atomic rights | Не требуются | Замена SUID, контейнеры |
| **Seccomp** | Syscall | Допустимые вызовы ядру | Не требуются | Снижение поверхности атаки |
| **AppArmor** | Пути/ресурсы | Доступ по профилям | Не требуются | Мандатный контроль (файлы, сокеты) |
| **SELinux** | Контексты | Метки и домены | CAP_MAC_ADMIN | Строгий MAC (многоуровневый) |
| **Landlock** | ФС/сеть | Песочница приложения | Не требуются | Self-sandboxing без root |

### Преимущества и ограничения

**Преимущества:**
*   **Гранулярность:** Замена полного `root` на отдельные права (например, только `CAP_NET_BIND_SERVICE`).
*   **Безопасность:** Принцип наименьших привилегий снижает взрывную силу при RCE.
*   **Прозрачность:** Реализованы в ядре, работают на уровне потоков, не требуют userspace-демонов.
*   **Совместимость:** Поддерживаются всеми современными runtime (Docker, Podman, systemd, Kubernetes).
*   **File capabilities:** Позволяют бинарникам получать права без SUID-бита и без запуска всего процесса от root.
*   **Ambient:** Передача прав скриптам и интерпретаторам, не поддерживающим файловые возможности.

**Ограничения:**
*   **Порог входа:** Необходимо знать, какие capabilities нужны конкретному приложению (требует аудита).
*   **Не всё покрывается:** Нет capability для «только чтение /etc/passwd» — для этого нужен LSM (AppArmor/SELinux) или Landlock.
*   **CAP_SYS_ADMIN:** По-прежнему даёт слишком много прав; его использование в контейнерах эквивалентно практически неограниченному доступу.
*   **User Namespace нюансы:** Наборы capabilities внутри user namespace могут отличаться от хостовых; требуется понимание контекста.
*   **Взаимодействие с LSM:** Capabilities не заменяют AppArmor/SELinux — они дополняют друг друга.

## Практические сценарии

### 1. Аудит и просмотр привилегий

**Просмотр текущего процесса:**
```bash
capsh --print
# → Current: = cap_net_bind_service+i
# → Bounding set =cap_chown,cap_dac_override...
```

**Просмотр работающего процесса:**
```bash
getpcaps <PID>
```

**Проверка file capabilities бинарника запущенного процесса:**
```bash
getcap $(readlink -f /proc/<PID>/exe)
# → /usr/sbin/nginx cap_net_bind_service=ep
```
Ссылка `/proc/<PID>/exe` указывает на фактический исполняемый файл, загруженный ядром через `execve()`, тогда как путь из `cmdline` (`argv[0]`) может быть подменен или вести на удаленный файл (подробнее — [procfs](../../FileSystems/virtual_fs_proc.md)). Непривилегированный процесс (UID != 0) может получить привилегированные операции через file capabilities своего бинарника (`cap_net_admin`, `cap_dac_override` и т.д.), поэтому при аудите и расследовании проверяются оба уровня: наборы capabilities самого процесса (`getpcaps`, `CapEff` в `/proc/PID/status`) и file capabilities его executable (`getcap`).

**Проверка поддержки ядром:**
```bash
grep Cap /proc/self/status
# Выводит маски наборов в шестнадцатеричном формате
```

### 2. Диагностика: два root-процесса с разными правами

Классическая ловушка: на одном хосте два контейнера из одного образа, в обоих `id` показывает `uid=0(root)`, файл принадлежит root и имеет права `000` (`----------`) — но первый контейнер читает его, а второй получает `Permission denied`. Причина: одинаковый UID не означает одинаковый набор capabilities.

**Воспроизведение:**
```bash
# Контейнер 1 — стандартный набор capabilities Docker
docker run -d --name c1 alpine sleep infinity
# Контейнер 2 — из того же образа, но без одной capability
docker run -d --name c2 --cap-drop DAC_OVERRIDE alpine sleep infinity

# В обоих контейнерах: владелец root, прав нет вообще
ls -l /secret
# → ---------- 1 root root 12 ... /secret

cat /secret
# c1: содержимое файла
# c2: cat: can't open '/secret': Permission denied
```

**Поиск различия через /proc.** Состояние процесса доступно напрямую через procfs, без специальных утилит Docker:
```bash
grep CapEff /proc/$$/status   # $$ — PID текущего шелла
# c1: CapEff:	00000000a80425fb
# c2: CapEff:	00000000a80425f9
```
Маски выглядят как случайные hex-строки, но это обычные битовые поля: каждый бит соответствует одной capability. Разница видна в последнем байте (`fb` против `f9`). Чтобы найти отличающийся бит без визуального сравнения портянок, применяется XOR (побитовое исключающее ИЛИ: одинаковые биты дают 0, различающиеся — 1; все совпадающие части масок обнулятся):
```bash
printf '%x\n' $((0xa80425fb ^ 0xa80425f9))
# → 2
```
Результат `2` — не «количество отличий», а новая битовая маска в hex. В двоичном виде это `10`: установлен ровно один бит — второй. Название capability подскажет `capsh`:
```bash
capsh --decode=2
# → 0x0000000000000002=cap_dac_override
```
Нумерация capabilities начинается с нуля: `CAP_DAC_OVERRIDE` имеет номер 1 (занимает второй бит), а маска второго бита — `0x2`. Проверить можно по заголовочному файлу ядра:
```bash
grep define CAP_DAC_OVERRIDE /usr/include/linux/capability.h
# → #define CAP_DAC_OVERRIDE 1
```

Итог эксперимента: у первого процесса бит `CAP_DAC_OVERRIDE` в `CapEff` установлен, у второго — сброшен флагом `--cap-drop DAC_OVERRIDE`. Образ, UID и права файла одинаковы — отличается ровно один бит в credentials процесса. Это же видно и в Kubernetes через `securityContext.capabilities`.

### 3. Механизм проверки: путь системного вызова openat()

Runtime (Docker) — userspace-программа: он настраивает credentials процесса при запуске (UID, GID, capability set), но не сидит между процессом и файлом и не участвует в каждой проверке доступа. Решение в конечном итоге принимает ядро. Упрощённый путь чтения файла `/secret` утилитой `cat` (которая сама по себе диск не читает, а просит ядро открыть файл):

```text
cat /secret → syscall openat() → VFS → проверка прав inode → обычная DAC-проверка (биты rwx)
→ проверка CAP_DAC_OVERRIDE в CapEff → файл открыт | EACCES (Permission denied)
```

1.  Ядро сначала смотрит на обычные DAC-права (Discretionary Access Control — те самые права владельца/группы/остальных из `ls -l`). Для файла с правами `000` чтение не разрешено никому.
2.  Затем ядро проверяет credentials текущего процесса: есть ли в `CapEff` полномочие, позволяющее обойти эту проверку. У первого контейнера бит установлен — файл открывается; у второго сброшен — обходить DAC-проверку нечем, ядро возвращает отказ.

Важные оговорки:
*   Это не полный список проверок перед открытием файла: capabilities — не универсальный пропуск. `CAP_DAC_OVERRIDE` обходит конкретный класс проверок (обычные файловые права), но процесс автоматически не обойдёт SELinux/AppArmor или seccomp — эти слои работают независимо и могут запретить операцию независимо от набора capabilities процесса.

### 4. Управление возможностями файлов

Используется для замены опасного SUID-бита гранулярными правами.

```bash
# Разрешить утилите ping создавать raw-сокеты без root
sudo setcap 'cap_net_raw+ep' /usr/bin/ping

# Разрешить веб-серверу занимать порты < 1024
sudo setcap 'cap_net_bind_service=+ep' /usr/bin/node

# Просмотр установленных прав
getcap /usr/bin/ping
# → /usr/bin/ping cap_net_raw=ep

# Удаление всех прав
sudo setcap -r /usr/bin/node
```

**Флаги:** `e` (Effective), `p` (Permitted), `i` (Inheritable).

### 5. Опасные возможности (Векторы LPE)

Некоторые возможности фактически эквивалентны полному `root`-доступу:

| Capability | Почему опасна |
| :--- | :--- |
| `CAP_SYS_ADMIN` | "Универсальный ключ". Позволяет монтировать ФС, настраивать сеть, менять лимиты. |
| `CAP_DAC_OVERRIDE` | Полный обход прав доступа к файлам (чтение `/etc/shadow`). |
| `CAP_SETUID` / `CAP_SETGID` | Позволяет процессу изменить свой UID/GID на 0. |
| `CAP_SYS_PTRACE` | Позволяет внедрять код в другие процессы (например, в shell администратора). |
| `CAP_SYS_MODULE` | Позволяет загружать модули ядра (полный захват Ring 0). |

**Поиск векторов атаки:**
```bash
# Поиск файлов с возможностями по всей системе
getcap -r / 2>/dev/null
```

### 6. Использование в контейнерах

В Docker и Kubernetes по умолчанию используется безопасный набор возможностей (около 14 из 40+). Ни Docker, ни Kubernetes не изобретают собственной функциональности: они лишь настраивают обычные Linux credentials процесса (UID/GID + capability sets) через container runtime, а окончательное решение при каждой операции принимает ядро. Поэтому вопрос «контейнер работает от root или нет» сам по себе мало что говорит о его реальных возможностях — полезнее спрашивать, какие capabilities у процесса есть на самом деле.

#### Docker

Два основных флага:
```bash
--cap-add NET_ADMIN   # добавить capability
--cap-drop MKNOD      # убрать capability
--cap-drop=ALL        # убрать весь исходный набор
```
При `--cap-drop=ALL` процесс всё ещё может стартовать с UID 0, но исходный набор capabilities у него будет изъят.

`--privileged` — не просто сокращение для `--cap-drop=ALL --cap-add=ALL`: он дополнительно расширяет доступ к устройствам хоста и ослабляет другие ограничения контейнера (seccomp, AppArmor/SELinux). Подробнее о рисках — [Hardening контейнеров](../../../Docker/Docker_security/container_hardening.md).

#### Kubernetes

Отдельной системы capabilities в Kubernetes нет — используется стандартный `securityContext`. Обратите внимание: названия указываются без префикса `CAP_` (`DAC_OVERRIDE`, а не `CAP_DAC_OVERRIDE`). Процесс может иметь UID 0, но нужного полномочия в его credentials уже не будет:

```yaml
securityContext:
  runAsNonRoot: true               # требует запуска не с UID 0
  runAsUser: 10001                 # явный стартовый UID (однозначное поведение)
  allowPrivilegeEscalation: false  # runtime выставит флаг ядра no_new_privs
  capabilities:
    drop: ["ALL"]                  # сначала выкинуть весь исходный набор
    add: ["NET_BIND_SERVICE"]      # вернуть только реально нужное
  seccompProfile:
    type: RuntimeDefault           # профиль предоставляет runtime (containerd, Docker)
```

*   `allowPrivilegeEscalation: false` просит runtime выставить процессу Linux-флаг `no_new_privs`, чтобы через `execve()` нельзя было получить больше привилегий, чем у родителя.
*   `seccompProfile: RuntimeDefault` включает стандартный security profile: seccomp фильтрует системные вызовы, то есть даже при наличии нужной capability сам syscall может быть запрещён профилем.
*   Kubernetes передаёт эту конфигурацию container runtime, runtime настраивает обычный Linux-процесс, дальше решение принимает ядро.

#### Почему это важно для безопасности

При RCE-уязвимости в приложении никакого специального «режима хакера» не включается: код выполняется в контексте существующего процесса и наследует его UID, namespaces и capabilities. Поэтому критично, какие capabilities остались у процесса. Компрометация процесса с минимальным набором capabilities и процесса с `CAP_SYS_ADMIN` + `CAP_SYS_PTRACE` + `CAP_NET_ADMIN` — две совершенно разные стартовые позиции для атакующего.

При этом сама по себе capability не является уязвимостью, а `CAP_SYS_ADMIN` не означает автоматический container escape. Но каждая лишняя capability открывает процессу дополнительные привилегированные операции и увеличивает количество вариантов дальнейшей атаки: до взлома этими правами пользуется приложение, после взлома — атакующий. Отсюда базовый подход: сначала выкидывается всё (`drop: ALL`), затем возвращаются только те привилегии, без которых приложение не работает (например, `NET_BIND_SERVICE` для прослушивания привилегированного порта).

### 7. Интеграция с systemd

systemd предоставляет два параметра для управления capabilities в unit-файлах:

*   **`CapabilityBoundingSet=`:** Максимальный набор capabilities, доступных сервису. Остальные capabilities из bounding set хоста не попадут в процесс.
*   **`AmbientCapabilities=`:** Набор capabilities, которые система добавит в Ambient-набор процесса при старте. Полезно для сервисов, которые не могут использовать файловые возможности (скрипты, интерпретаторы).

```ini
# /etc/systemd/system/myapp.service
[Service]
Type=simple
User=app
Group=app

# Ограничиваем bounding set только нужными возможностями
CapabilityBoundingSet=CAP_NET_BIND_SERVICE CAP_SETUID

# Передаём нужную capability через Ambient
AmbientCapabilities=CAP_NET_BIND_SERVICE

# Запрещаем повышение привилегий
NoNewPrivileges=true

ExecStart=/usr/local/bin/myapp --config /etc/myapp/config.yaml

# Проверка конфигурации
systemctl daemon-reload
systemctl start myapp
```

**Проверка:**
```bash
# Убедиться, что сервис получил только разрешённые capabilities
systemctl show myapp --property=CapabilityBoundingSet,AmbientCapabilities
# → CapabilityBoundingSet=cap_net_bind_service cap_setuid
# → AmbientCapabilities=cap_net_bind_service

# Проверка через /proc
grep -E 'Cap(Prm|Eff|Inh|Bnd|Amb)' /proc/$(pgrep myapp)/status
```

### 8. Управление через libcap (программный метод)

Установка прав через `setcap` подходит для бинарных файлов, но для динамически создаваемых приложений или runtime-сред удобнее использовать библиотеку `libcap`.

```c
#include <sys/capability.h>
#include <unistd.h>
#include <stdio.h>

int main() {
    cap_t caps = cap_get_proc();
    if (!caps) {
        perror("cap_get_proc");
        return 1;
    }

    char *text = cap_to_text(caps, NULL);
    printf("Current capabilities: %s\n", text);
    cap_free(text);

    cap_t newcaps = cap_init();
    cap_value_t cap_list[] = {CAP_NET_BIND_SERVICE, CAP_CHOWN};

    cap_set_flag(newcaps, CAP_EFFECTIVE, 2, cap_list, CAP_SET);
    cap_set_flag(newcaps, CAP_PERMITTED, 2, cap_list, CAP_SET);

    if (cap_set_proc(newcaps) == -1) {
        perror("cap_set_proc");
        return 1;
    }

    cap_free(newcaps);
    cap_free(caps);

    printf("Capabilities updated successfully\n");
    return 0;
}
```

```bash
# Сборка
gcc -o cap_demo cap_demo.c -lcap

# Запуск без root
./cap_demo
# → Current capabilities: = cap_net_bind_service+ep
# → Capabilities updated successfully
```

**Важно:** Для установки некоторых caps (например, `CAP_SYS_ADMIN`) процесс должен запускаться от root или иметь соответствующую возможность в bounding set.

### 9. Устранение неисправностей

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Permission denied` при чтении файла | В `CapEff` нет `CAP_DAC_OVERRIDE` | Проверьте bounding set и permitted set процесса |
| `Operation not permitted` при `setcap` | Недостаточно прав (не root) | Запустите через `sudo` или от имени пользователя с нужной capability |
| File capabilities сбросились после копирования | Файловая система не поддерживает xattr | Используйте `cp --preserve=xattr` или проверьте `mount` опции |
| `capsh --print` показывает пустой Effective | Process был запущен с `no_new_privs` или из deprived container | Проверьте `NoNewPrivs` в `/proc/PID/status` |
| Container не может привязаться к порту < 1024 | Не добавлена `CAP_NET_BIND_SERVICE` | Добавьте `--cap-add NET_BIND_SERVICE` в Docker |
| `getcap` показывает `=` вместо `ep` | У файла нет установленных file capabilities | Установите через `sudo setcap 'cap_xxx+ep' /path` |
| Capabilities не наследуются через `execve()` | Набор `Inheritable` пуст, `Ambient` не настроен | Настройте `Ambient` или file capabilities бинарника |

### 10. Профилирование и аудит

Для SRE-сценариев полезно выявлять процессы с избыточными capabilities и строить минимальные профили.

```bash
# Полный снимок capabilities всех процессов
for pid in $(ls /proc | grep -E '^[0-9]+$'); do
    name=$(cat /proc/$pid/comm 2>/dev/null)
    caps=$(grep -E '^Cap(Prm|Eff|Inh|Bnd|Amb)' /proc/$pid/status 2>/dev/null | tr '\n' ' ')
    echo "$pid $name $caps"
done | column -t

# Поиск процессов с CAP_SYS_ADMIN
ps -e -o pid,comm,capEff | awk '$3 ~ /ffffffff/ {print $0}'

# Аудит файловых возможностей (исключая системные пути)
getcap -r /usr/local /opt /home 2>/dev/null

# Проверка, какие capabilities требует приложение (strace + capsh)
strace -e trace=capabilities ./my-app 2>&1 | grep -i cap | head -20
```

**Автоматизация через auditd:**
```bash
# Правило для логирования всех setcap/setuid операций
auditctl -a always,exit -F arch=b64 -S setcap -k capability_change

# Чтение логов
ausearch -k capability_change -i
```

## Дополнительная информация

### Инструменты и пакеты

| Пакет / Утилита | Назначение | Пример использования |
| :--- | :--- | :--- |
| `libcap` / `libcap-ng` | Программное управление capabilities из C/Go/Python | `cap_set_proc()`, `cap_get_proc()` |
| `capsh` | Оболочка для отладки capabilities | `capsh --print`, `capsh --decode=2` |
| `getcap` / `setcap` | Просмотр и установка файловых возможностей | `getcap /usr/bin/ping` |
| `getpcaps` | Просмотр capabilities процесса по PID | `getpcaps <PID>` |
| `procps` / `ps` | Стандартный вывод процессов с масками caps | `ps -e -o pid,comm,capEff` |
| `auditd` / `auditctl` | Аудит изменения capabilities и syscalls | `auditctl -a always,exit -S setcap` |
| `strace` | Трассировка syscalls и capabilities | `strace -e trace=capabilities ./app` |
| `libseccomp` | Взаимодействие с seccomp (комплементарно) | `seccomp_rule_add()` |
| `bpftool` | Инспекция eBPF-программ (контекст LSM/BPF) | `bpftool prog list` |

### Матрица совместимости: Capabilities и Workload

| Workload | Минимальные capabilities | Типичные исключения | Рекомендация |
| :--- | :--- | :--- | :--- |
| **Go-сервис** | `NET_BIND_SERVICE` (если порт < 1024) | Нет | Установить file capabilities или Ambient |
| **nginx / Apache** | `NET_BIND_SERVICE` | Нет | `setcap cap_net_bind_service=+ep /usr/sbin/nginx` |
| **PostgreSQL / MySQL** | `IPC_LOCK` (для mlock), `SYS_RESOURCE` (для ulimit) | Нет | Использовать `CapabilityBoundingSet=` в systemd |
| **Node.js / Python** | Нет (по умолчанию) | `SYS_ADMIN`, `NET_ADMIN` | Избегать `--privileged` в Docker |
| **SSH-сервер** | `SYS_ADMIN` (для `utmp`), `SETUID`/`SETGID` | Ограничить bounding set | `CapabilityBoundingSet=CAP_SYS_ADMIN CAP_SETUID CAP_SETGID` |
| **Java-приложение** | Нет (обычно) | `SYS_ADMIN` | Проверить `ulimit -a` и `/proc/PID/limits` |
| **Системный сервис (systemd)** | Зависит от сервиса | `ALL` → явный allow-list | `CapabilityBoundingSet=` + `AmbientCapabilities=` |
| **Rootless-контейнер** | `NET_BIND_SERVICE` (опционально) | `SYS_ADMIN` | File capabilities внутри контейнера |
| **CI/CD раннер** | Нет (по умолчанию) | `ALL` | `no_new_privs`, `cap_drop=ALL` |

### Уровни совместимости

| Обозначение | Описание |
| :--- | :--- |
| **[OK]** | Стандартный профиль работает без изменений. |
| **[!]** | Требуется добавление 1–5 capabilities. |
| **[BLOCKED]** | Требуется критическая capability (`SYS_ADMIN`, `SYS_MODULE`), которая не может быть безопасно предоставлена. |

### Ограничения и архитектурные нюансы

1.  **Не универсальный контроль доступа:** Capabilities решают задачу «что процесс может делать», но не «куда процесс может лезть». Для контроля над путями файлов, сетевыми портами или контекстом процесса используются LSM (AppArmor, SELinux) или Landlock.
2.  **CAP_SYS_ADMIN — король возможностей:** Право `CAP_SYS_ADMIN` исторически накапливало всё новые под-полномочия (mount, namespaces, perf, bpf). В 2024–2026 годах ядро активно выносит отдельные capabilities (`CAP_BPF`, `CAP_PERFMON`, `CAP_CHECKPOINT_RESTORE`), но `CAP_SYS_ADMIN` остаётся слишком широким для production.
3.  **User Namespace и привилегии:** Внутри user namespace процесс может иметь «полный» набор capabilities, но эти права действуют только в пределах namespace. Для хоста такой процесс непривилегирован. Это обеспечивает безопасность Rootless Docker/Podman.
4.  **no_new_privs и Ambient:** NNP блокирует SUID и файловые возможности, но НЕ трогает Ambient-набор. Это делает Ambient единственным способом передать capability через `execve()` в hardened-среде.
5.  **Взаимодействие с Seccomp:** Даже если у процесса есть `CAP_NET_ADMIN`, seccomp-профиль может запретить соответствующий syscall. Механизмы работают независимо: сначала Seccomp проверяет, разрешён ли вызов, затем capabilities проверяют, имеет ли процесс право на операцию.
6.  **Производительность:** Проверка capabilities в hot-path ядра имеет минимальные накладные расходы (проверка битовых масок), но слишком частые вызовы `capget()`/`capset()` из userspace могут влиять на производительность в высоконагруженных системах.
7.  **VFS capability version:** Контейнеры на новом хосте с V3 атрибутами могут не передавать file capabilities корректно на старые ядра (V2). При миграции образов проверяйте версию VFS.

### Взаимодействие с User Namespaces

Внутри User Namespace процесс может иметь "полные" capabilities (например, `CAP_SYS_ADMIN`), которые позволяют ему управлять ресурсами *внутри* этого пространства имен (монтировать временные ФС, настраивать виртуальную сеть). Однако для основного ядра (Host) этот процесс остается непривилегированным. Это основа работы **Rootless Docker/Podman**.

### См. также
- [Обзор механизмов безопасности Linux](../Linux_Security_Mechanisms_Overview.md)
- [Seccomp: фильтрация системных вызовов](./Seccomp.md)
- [Landlock: современная песочница ФС](./Landlock.md)
- [Безопасность модулей ядра](./kernel_module_security.md) — подпись и контроль загрузки модулей
