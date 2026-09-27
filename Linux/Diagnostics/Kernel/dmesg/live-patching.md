# Диагностика live patching через dmesg

## Определения

**Сообщения live patching в dmesg** — выводы ядра, отражающие процесс применения исправлений к работающему ядру без перезагрузки: загрузку патч-модулей, переключение функций (function patching), откат патчей и ошибки совместимости. Механизмы live patching: kpatch (RHEL), kGraft/SUSE Live Patch, Canonical Livepatch, upstream ftrace-based livepatch.

---

## Базовые концепции

### Механизм live patching

```
Ядро (running)
  ↓ Загрузка патч-модуля (.ko)
  ↓ Регистрация патча через livepatch
  ↓ ftrace: переключение address на новую функцию
  ↓ Все новые вызовы идут через новую функцию
  ↓ Откат при необходимости
```

### Типы сообщений в dmesg

| Сообщение | Тип | Описание |
|:---|:---|:---|
| `livepatch: module: 'name' loaded` | Info | Патч-модуль успешно загружен |
| `livepatch: 'name': starting patch` | Info | Начало применения патча |
| `livepatch: 'name': patching complete` | Info | Патч успешно применён |
| `livepatch: 'name': reverting patch` | Info | Откат патча |
| `livepatch: 'name': revert complete` | Info | Откат завершён |
| `livepatch: 'name': failed to apply` | Error | Ошибка применения патча |
| `livepatch: 'name': tainted module` | Warning | Патч вызвал taint ядра |

---

## Практические сценарии

### Поиск событий live patching в dmesg

```bash
# Все события live patching
dmesg -T | grep -iE "livepatch|kpatch|kpatch.*module|ftrace.*patch"

# Только ошибки
dmesg -T | grep -iE "livepatch.*error|livepatch.*fail|kpatch.*error"

# История применённых патчей
dmesg -T | grep -iE "livepatch.*loaded|livepatch.*complete|livepatch.*revert"
```

### Диагностика kpatch

```bash
# Проверка kpatch-модулей
dmesg | grep -iE "kpatch|kpatch.*module|kpatch.*func"

# Ключевые паттерны:
# -> kpatch: loaded patch module 'kpatch-CVE-2024-XXXX'
# -> kpatch: patching function 'tcp_sendmsg'
# -> kpatch: func 'tcp_sendmsg' replaced at 0xffffffff81234567

# Проверка статуса kpatch
kpatch list
# -> LOAD MODULE          NAME             STATUS
# -> /lib/modules/...     kpatch-CVE-...   enabled

# Ошибки kpatch
dmesg | grep -iE "kpatch.*error|kpatch.*fail|kpatch.*reject"

# Типичные ошибки:
# -> kpatch: function 'xyz' not found
# -> kpatch: patched function 'xyz' has been modified
# -> kpatch: incompatible feature flags
```

### Диагностика Canonical Livepatch

```bash
# Проверка livepatch через canonical-livepatch
canonical-livepatch status 2>/dev/null
# -> status: kernel is livepatched
# -> fix-cve-2024-xxxx: applied

# Проверка через dmesg
dmesg | grep -iE "livepatch|canonical"

# Ключевые паттерны:
# -> livepatch: module: canonical_livepatch loaded
# -> livepatch: 'canonical_livepatch': patching complete
```

### Диагностика ftrace-based livepatch

```bash
# Проверка ftrace переключений
dmesg | grep -iE "ftrace|trace.*patch|function.*hook"

# Ключевые паттерны:
# -> livepatch: reverting function 'do_sys_open'
# -> livepatch: patching function 'do_sys_open'

# Проверка через ftrace
cat /sys/kernel/debug/tracing/available_filter_functions | grep "livepatch"
```

### Диагностика проблем совместимости

```bash
# Проверка версии ядра
uname -r

# Проверка, какой патч загружен
dmesg | grep -iE "livepatch.*version|livepatch.*kernel"

# Если патч несовместим:
# -> livepatch: module: 'patch' version mismatch
# -> livepatch: 'patch': incompatible with kernel

# Решение:
# 1. Скачать патч для текущей версии ядра
# 2. Или обновить ядро до версии, для которой есть патч
```

### Откат live patch

```bash
# Откат конкретного патча
kpatch unload kpatch-CVE-2024-XXXX 2>/dev/null

# Проверка отката в dmesg
dmesg | grep -iE "livepatch.*revert|livepatch.*unload"

# Ключевые паттерны:
# -> livepatch: 'patch': reverting patch
# -> livepatch: 'patch': revert complete
# -> livepatch: module 'patch' unloaded
```

---

## Дополнительная информация

### Связанные темы

*   [**Live Patching**](../../../Core/kernel/live_patching.md) — полный обзор механизмов live patching.
*   [**kexec**](../../../Core/kernel/live_patching.md#kexec) — kexec для быстрой перезагрузки.
*   [**Kernel Modules**](../../../Core/kernel/kernel_modules.md) — жизненный цикл модулей ядра.
*   [**Обзор dmesg**](./index.md) — общая архитектура kmsg.
*   [**Поиск и устранение неисправностей**](./troubleshooting.md) — Call Trace, Oops, Panic.
*   [**Vulnerability Management**](../../../Security/vulnerability_management.md) — управление уязвимостями.
