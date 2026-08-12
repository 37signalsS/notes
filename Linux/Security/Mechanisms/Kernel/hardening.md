# Харденинг ядра Linux

## Определения

**Харденинг ядра (Kernel Hardening)** — комплекс мер по настройке конфигурации и параметров ядра Linux для минимизации поверхности атаки, предотвращения эксплуатации известных классов уязвимостей (LPE, Memory Corruption) и ограничения возможностей злоумышленника на этапе пост-эксплуатации.

**KSPP (Kernel Self-Protection Project)** — инициатива сообщества по внедрению в основную ветку ядра технологий, которые делают эксплуатацию ошибок безопасности экономически невыгодной или технически невозможной.

**Kernel Lockdown** — модуль безопасности (LSM), ограничивающий доступ к функциям ядра, которые могут быть использованы для обхода Secure Boot или модификации образа работающего ядра (даже пользователем `root`).

## Основные концепции

### 1. Защита памяти и предотвращение эксплуатации

Современные ядра (6.x/7.0) включают механизмы для борьбы с Corruption-атаками:
*   **Memory Sanitization**: Очистка страниц при выделении или освобождении (`init_on_alloc=1`, `init_on_free=1`) предотвращает утечку данных через Use-After-Free.
*   **Shadow Stack (CET / Shadow Stack)**: Аппаратная поддержка предотвращения перезаписи адреса возврата в стеке (защита от ROP-цепочек).
*   **SLAB_FREELIST_HARDENED**: Рандомизация и проверка целостности списков свободных блоков в аллокаторе памяти.
*   **STACKLEAK**: Очистка системного стека перед возвратом из системного вызова в пространство пользователя.

### 2. Режимы Kernel Lockdown

Активируется через параметр загрузки `lockdown=...` или при включенном Secure Boot:
*   **Integrity**: Блокирует прямую запись в `/dev/mem`, использование `kexec` неподписанных ядер, доступ к отладочным интерфейсам процессора (MSR).
*   **Confidentiality**: Включает `Integrity` + запрещает чтение памяти ядра (защита ключей и секретов).

### 3. Ограничение подсистем (Attack Surface Reduction)

*   **eBPF**: Из-за сложности и потенциальных JIT-уязвимостей доступ для непривилегированных пользователей должен быть закрыт.
*   **User Namespaces**: Несмотря на пользу для контейнеров, механизм часто используется в цепочках LPE-эксплуатации.
*   **Legacy Interfaces**: Отключение старых сетевых протоколов (DCCP, SCTP) и TTY-дисциплин.

## Практические сценарии

### 1. Эталонная конфигурация sysctl (2026)

Создайте файл `/etc/sysctl.d/99-kernel-hardening.conf` для применения при загрузке:

```bash
# --- Защита от LPE и инспекции памяти ---
kernel.kptr_restrict = 2            # Скрыть адреса ядра в /proc/kallsyms
kernel.dmesg_restrict = 1           # Запрет чтения dmesg обычным пользователям
kernel.perf_event_paranoid = 3      # Максимальное ограничение подсистемы perf
kernel.yama.ptrace_scope = 2        # Разрешить ptrace только для дочерних процессов (или root)
kernel.unprivileged_bpf_disabled = 1 # Отключить eBPF для пользователей
net.core.bpf_jit_harden = 2         # Постоянная JIT-защита для всех процессов

# --- Защита адресного пространства (ASLR) ---
kernel.randomize_va_space = 2
vm.mmap_rnd_bits = 32               # Усиление рандомизации mmap (для x86_64)

# --- Ограничение User Namespaces (если не используются) ---
# kernel.unprivileged_userns_clone = 0 # Для Debian/Ubuntu

# --- Защита от атак через файловые дескрипторы ---
fs.protected_fifos = 2
fs.protected_regular = 2
fs.protected_symlinks = 1
fs.protected_hardlinks = 1
```

### 2. Параметры загрузки ядра (GRUB)

Добавьте в `GRUB_CMDLINE_LINUX_DEFAULT`:
```text
lockdown=integrity slab_nomerge init_on_alloc=1 init_on_free=1 pti=on page_alloc.shuffle=1
```

### 3. Запрет загрузки опасных модулей

```bash
# /etc/modprobe.d/security-blacklist.conf
install dccp /bin/true
install sctp /bin/true
install rds /bin/true
install tipc /bin/true
install firewire-core /bin/true
install thunderbolt /bin/true
```

## SCA: Проверка харденинга в Wazuh

SCA-политика для автоматизированного контроля параметров ядра.

**Файл:** `/var/ossec/etc/custom_scripts/sca_kernel_hardening.yml`

```yaml
policy:
  id: "kernel_hardening"
  file: "kernel_hardening.yml"
  name: "Kernel Hardening Compliance 2026"
  description: "Checks kernel parameters according to KSPP and modern best practices"
  regex_type: "pcre2"

requirements:
  title: "Check that the target is a Linux system"
  condition: all
  rules:
    - 'f:/proc/sys/kernel/ostype -> r:Linux'

checks:
  - id: 100001
    title: "kernel.kptr_restrict should be 2"
    rules:
      - 'f:/proc/sys/kernel/kptr_restrict -> 2'
  - id: 100002
    title: "kernel.dmesg_restrict should be 1"
    rules:
      - 'f:/proc/sys/kernel/dmesg_restrict -> 1'
  - id: 100003
    title: "kernel.unprivileged_bpf_disabled should be 1"
    rules:
      - 'f:/proc/sys/kernel/unprivileged_bpf_disabled -> 1'
  - id: 100004
    title: "Kernel lockdown mode should be enabled (integrity/confidentiality)"
    rules:
      - 'f:/sys/kernel/security/lockdown -> r:\[(integrity|confidentiality)\]'
  - id: 100005
    title: "Yama ptrace_scope should be >= 1"
    rules:
      - 'f:/proc/sys/kernel/yama/ptrace_scope -> n:^(\d+) compare >= 1'
```

## Дополнительная информация

### Инструменты аудита
*   **kernel-hardening-checker**: Скрипт для проверки конфигурации ядра и параметров загрузки на соответствие рекомендациям KSPP.
*   **[Lynis](../../../Security/Tools/lynis.md)**: Проводит комплексный аудит безопасности системы, включая параметры ядра.

### См. также
- [KASLR (Kernel Address Space Layout Randomization)](../KASLR.md)
- [KPTI (Kernel Page Table Isolation)](../KPTI.md)
- [Linux Capabilities](../Capabilities.md)
- [auditd: аудит системных вызовов](../../SystemAdministration/Logging/auditd.md)
- [Мониторинг ядра через Wazuh](../../../Security/Tools/Wazuh/kernel_monitoring.md)
