# Харденинг ядра Linux

## Определения

**Харденинг ядра (Kernel Hardening)** — процесс настройки параметров ОС и ядра для минимизации поверхности атаки, предотвращения эксплуатации уязвимостей (LPE, Memory Corruption) и ограничения возможностей злоумышленника после проникновения.

**Kernel Lockdown** — механизм безопасности, запрещающий любые действия, которые могут позволить коду в пространстве пользователя изменять образ работающего ядра или получать доступ к конфиденциальным данным ядра (даже пользователю root).

## Основные концепции

### Защита от атак класса Page Cache Write (Dirty Frag, Copy Fail)

Для минимизации риска эксплуатации уязвимостей, использующих `splice()` и криптографические сокеты, необходимо ограничить доступ к отладочным интерфейсам и неиспользуемым подсистемам.

#### Параметры sysctl

| Параметр | Рекомендуемое значение | Описание |
| :--- | :--- | :--- |
| `kernel.kptr_restrict` | `2` | Полностью скрывает адреса структур ядра в `/proc/kallsyms`. |
| `kernel.dmesg_restrict` | `1` | Запрещает непривилегированным пользователям читать `dmesg`. |
| `kernel.perf_event_paranoid` | `3` | Максимально ограничивает доступ к подсистеме `perf`. |
| `kernel.unprivileged_userns_clone` | `0` | (Debian/Ubuntu) Отключает создание user namespaces обычными пользователями. |
| `kernel.modules_disabled` | `1` | Запрещает загрузку новых модулей после старта системы. |

### Режимы Lockdown

Настраивается через параметр загрузки ядра `lockdown=...`:
- **none**: Механизм отключен.
- **integrity**: Запрещаются операции, позволяющие изменять работающее ядро (например, запись в `/dev/mem`, использование `kexec` без проверки подписи).
- **confidentiality**: Включает `integrity` + запрещает извлечение конфиденциальных данных из памяти ядра.

## Практические сценарии

### Сценарий 1: Конфигурация для защиты от LPE

```bash
# Создайте файл /etc/sysctl.d/99-kernel-hardening.conf
kernel.kptr_restrict = 2
kernel.dmesg_restrict = 1
kernel.perf_event_paranoid = 3
kernel.unprivileged_userns_clone = 0
dev.tty.ldisc_autoload = 0
vm.unprivileged_userfaultfd = 0
```

### Сценарий 2: Митигация Dirty Frag / Copy Fail

Если специфические модули не используются, их следует заблокировать на уровне загрузчика:

```bash
# /etc/modprobe.d/security-blacklist.conf
install xfrm_user /bin/true
install af_alg /bin/true
install rxrpc /bin/true
```

## SCA: Проверка харденинга в Wazuh

SCA-политика для автоматизированного контроля параметров ядра.

**Файл:** `/var/ossec/etc/custom_scripts/sca_kernel_hardening.yml`

```yaml
policy:
  id: "kernel_hardening"
  file: "kernel_hardening.yml"
  name: "Kernel hardening for Page-cache write vulnerabilities"
  description: "Checks kernel parameters that mitigate page-cache write attacks"
  regex_type: "pcre2"

requirements:
  title: "Check that the target is a Linux system"
  condition: all
  rules:
    - 'f:/proc/sys/kernel/ostype -> r:Linux'

checks:
  - id: 100001
    title: "kernel.kptr_restrict should be >= 1"
    rules:
      - 'f:/proc/sys/kernel/kptr_restrict -> n:^(\d+) compare >= 1'
  - id: 100002
    title: "kernel.dmesg_restrict should be 1"
    rules:
      - 'f:/proc/sys/kernel/dmesg_restrict -> 1'
  - id: 100003
    title: "kernel.perf_event_paranoid should be >= 2"
    rules:
      - 'f:/proc/sys/kernel/perf_event_paranoid -> n:^(\d+) compare >= 2'
  - id: 100004
    title: "Unprivileged user namespaces should be disabled"
    condition: any
    rules:
      - 'f:/proc/sys/kernel/unprivileged_userns_clone -> 0'
      - 'f:/proc/sys/user/max_user_namespaces -> 0'
  - id: 100005
    title: "Kernel lockdown mode should be enabled"
    rules:
      - 'f:/sys/kernel/security/lockdown -> r:\[(integrity|confidentiality)\]'
```

## Дополнительная информация

### См. также
- [auditd: аудит системных вызовов](../../SystemAdministration/Logging/auditd.md)
- [Мониторинг ядра через Wazuh](../../../Security/Tools/Wazuh/kernel_monitoring.md)
- [Wazuh: общая конфигурация](../../../Security/Tools/wazuh.md)
