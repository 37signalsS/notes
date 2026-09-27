# LD_PRELOAD: Безопасностный контекст

## Определения

**LD_PRELOAD** — переменная окружения, заставляющая динамический линковщик (`ld.so`) загружать указанные разделяемые библиотеки перед всеми остальными. Позволяет переопределять функции стандартных библиотек без перекомпиляции приложения.

**/etc/ld.so.preload** — файл, содержащий пути к библиотекам, загружаемым ПРИНУДИТЕЛЬНО для всех динамически линкуемых процессов. Аналог `LD_PRELOAD`, но глобальный и не зависит от переменных окружения.

**Library Injection (Инъекция библиотек)** — техника перехвата управления при запуске процесса путём подмены или дополнения стандартных библиотек через механизм предзагрузки.

**GOT/PLT Overwrite** — техника перезаписи таблицы GOT (Global Offset Table) для перенаправления вызовов функций на вредоносный код. Связана с LD_PRELOAD, так как предзагруженная библиотека может модифицировать GOT.

## Теоретический блок

### Механизм работы (кратко)

Полное описание механизма динамической линковки и LD_PRELOAD: **[Трассировка и отладка](../../Diagnostics/Troubleshooting/tracing_and_debugging.md#1-ld_preload-перехват-и-подмена-функций)**.

Порядок разрешения зависимостей (актуально для безопасности):
1. `DT_RPATH` / `DT_RUNPATH` в ELF-заголовке
2. `LD_LIBRARY_PATH` (игнорируется для setuid/setgid)
3. `/etc/ld.so.cache` (обновляется `ldconfig`)
4. Стандартные директории `/lib`, `/usr/lib`
5. **`/etc/ld.so.preload`** — загружается ПОСЛЕДНИМ, но ПЕРЕД всеми остальными

### Векторы атак

#### 1. Подмена через LD_PRELOAD (локальная эскалация)

Если атакующий может установить переменную окружения для процесса, выполняющегося с повышенными привилегиями, он может подменить любую функцию.

```bash
# Пример: подмена функции login() для обхода аутентификации
# Создание вредоносной библиотеки
cat > fake_auth.c << 'EOF'
#define _GNU_SOURCE
#include <dlfcn.h>
#include <string.h>

int pam_authenticate(void *handle, int flags) {
    return 0;  // Всегда возвращаем успех
}
EOF

gcc -shared -fPIC -o fake_auth.so fake_auth.c -ldl

# Запуск с подменой (если процесс не setuid)
LD_PRELOAD=./fake_auth.so /usr/bin/su
```

**Ограничение:** `LD_PRELOAD` и `LD_LIBRARY_PATH` игнорируются для **setuid/setgid** бинарников (защита ядра). Однако это не защищает от:
- Сервисов, запущенных через `systemd` без `NoNewPrivileges=yes`
- Процессов, которые уже拥有root и затемexecve() непривилегированный бинарник
- Сценариев с `LD_PRELOAD` в systemd-юнитах (run-as-root сервисы)

#### 2. Глобальная инъекция через /etc/ld.so.preload

Если атакующий получил write-доступ к `/etc/ld.so.preload`, он может внедрить библиотеку для **ВСЕХ** процессов на системе.

```bash
# Вредоносная запись (скрытый reverse shell)
echo "/tmp/.hidden/rootkit.so" > /etc/ld.so.preload
```

**Почему это опасно:**
- Работает даже для setuid-бинарников (файл загружается ядром напрямую)
- Невозможно обойти через `LD_PRELOAD=` (переменная окружения перезаписывается файлом)
- Поражает ВСЕ динамически линкуемые процессы

#### 3. Перехват iptables/nftables для снятия правил

```c
// Подмена функции iptables для логирования/блокировки правил
int main() {
    // Перехват вызова execve для iptables
    // Логирование всех изменений firewall
    // Возможность отката правил
}
```

#### 4. Перехват SSH-аутентификации

```c
// Подмена PAM-модуля через LD_PRELOAD
// Перехват pam_authenticate() для обхода проверки пароля
// Логирование учётных данных
```

### Связь с другими техниками

| Техника | Связь с LD_PRELOAD |
| :--- | :--- |
| **SUID-файлы** | LD_PRELOAD игнорируется для setuid, но `/etc/ld.so.preload` — нет |
| **Capabilities** | Процесс с `CAP_SYS_PTRACE` может внедрить LD_PRELOAD в другой процесс |
| **ptrace** | Через `ptrace(PTRACE_ATTACH)` можно модифицировать окружение целевого процесса |
| **systemd** | Юниты с `ProtectSystem=no` и `NoNewPrivileges=no` уязвимы |
| **Container Escape** | В контейнере с привилегиями LD_PRELOAD может влиять на хостовые процессы |

## Практический блок

### Обнаружение LD_PRELOAD в системе

```bash
# 1. Проверка глобального /etc/ld.so.preload
cat /etc/ld.so.preload
# → Должен быть пуст или содержать легитимные пути

# 2. Проверка окружения всех процессов
for pid in /proc/[0-9]*/; do
    pid_num=$(basename "$pid")
    preload=$(tr '\0' '\n' < "$pid/environ" 2>/dev/null | grep "^LD_PRELOAD=")
    if [ -n "$preload" ]; then
        echo "PID $pid_num: $preload"
    fi
done

# 3. Быстрая проверка через /proc
grep -r "LD_PRELOAD" /proc/*/environ 2>/dev/null | head -20

# 4. Проверка системных вызовов, связанных с ld.so
cat /proc/*/maps | grep "ld.so" | sort -u
```

### Обнаружение через auditd

```bash
# Мониторинг изменений /etc/ld.so.preload
auditctl -w /etc/ld.so.preload -p wa -k ld_preload_mod
auditctl -w /etc/ld.so.conf -p wa -k ld_config_mod

# Поиск событий
ausearch -k ld_preload_mod --start recent
```

### Защита

#### 1. systemd-изоляция

```ini
# /etc/systemd/system/hardened.service
[Service]
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
ReadOnlyPaths=/etc/ld.so.preload
ReadOnlyPaths=/etc/ld.so.conf
# Блокировка установки LD_PRELOAD через Environment
Environment="LD_PRELOAD="
```

#### 2. Kernel hardening (sysctl)

```bash
# Запрет use of LD_PRELOAD для непривилегированных процессов
# (ограничение — работает только для setuid)
sysctl -w fs.protected_hardlinks=1
sysctl -w fs.protected_symlinks=1
```

#### 3. Мониторинг через eBPF/Falco

```yaml
# Правило Falco для обнаружения LD_PRELOAD
- rule: Detect LD_PRELOAD Usage
  desc: Detect usage of LD_PRELOAD environment variable
  condition: >
    spawned_process and proc.env contains "LD_PRELOAD"
    and not proc.name in (allowed_preload_binaries)
  output: >
    LD_PRELOAD detected (user=%user.name command=%proc.cmdline
    parent=%proc.pname LD_PRELOAD=%proc.env[LD_PRELOAD])
  priority: WARNING
  tags: [defense_evasion, privilege_escalation]
```

#### 4. Политика доступа к /etc/ld.so.preload

```bash
# Только root может изменять
sudo chown root:root /etc/ld.so.preload
sudo chmod 644 /etc/ld.so.preload  # Не 600 — иначе ld.so не сможет прочитать

# Мониторинг через AIDE
echo "/etc/ld.so.preload hsha256" >> /etc/aide.conf
```

#### 5. Обнаружение через файловую целостность

```bash
# AIDE правило для /etc/ld.so.preload
# /etc/ld.so.preload sha256+c +permissions+user+group+size

# Tripwire правило
(/etc/ld.so.preload) -> Device = Static;
  # Contents = (sha256, rmd160);
  # Perms = 0644;
  # Owner = root;
  # Group = root;
```

### Диагностические команды

| Задача | Команда |
| :--- | :--- |
| Проверить `/etc/ld.so.preload` | `cat /etc/ld.so.preload` |
| Найти процессы с LD_PRELOAD | `grep -r "LD_PRELOAD" /proc/*/environ 2>/dev/null` |
| Проверить загруженные библиотеки процесса | `cat /proc/PID/maps \| grep "\.so"` |
| Проверить setuid-файлы | `find / -perm -4000 -type f 2>/dev/null` |
| Проверить capabilities | `getcap -r / 2>/dev/null` |
| Аудит /etc/ld.so.preload | `auditctl -w /etc/ld.so.preload -p wa -k preload` |

## Дополнительная информация

### Связанные темы

- **[Трассировка и отладка](../../Diagnostics/Troubleshooting/tracing_and_debugging.md)** — технический механизм LD_PRELOAD с примерами кода
- **[Управление библиотеками](../../Development/build_tools.md)** — RPATH, RUNPATH, ldconfig, LD_LIBRARY_PATH
- **[Kernel hardening](../Mechanisms/Kernel/hardening.md)** — sysctl-параметры для защиты
- **[Безопасность модулей ядра](../Mechanisms/kernel_module_security.md)** — подпись и контроль загрузки модулей
- **[Capabilities](../Mechanisms/Capabilities.md)** — `CAP_SYS_PTRACE` как вектор для LD_PRELOAD
- **[Systemd security](./systemd_security.md)** — изоляция сервисов
- **[File integrity checking](./file-integrity-checking.md)** — AIDE/Tripwire для мониторинга

### Стандарты

- **CIS Benchmark:** Рекомендация 5.3.4 — "Убедиться, что `/etc/ld.so.preload` не модифицирован"
- **STIG:** V-231725 — "Разрешенные файлы в `/etc/ld.so.preload` должны быть указаны"
