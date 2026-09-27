# Харденинг ядра Linux

## Определения

**Харденинг ядра (Kernel Hardening)** — комплекс мер по настройке конфигурации и параметров ядра Linux для минимизации поверхности атаки, предотвращения эксплуатации известных классов уязвимостей (LPE, Memory Corruption) и ограничения возможностей злоумышленника на этапе пост-эксплуатации.

**LKSPP (Linux Kernel Self-Protection Project)** — открытая инициатива разработчиков ядра Linux по внедрению технологий, делающих ядро устойчивым к эксплуатации даже при наличии привилегий у атакующего. Фокусируется на kernel-space.

**CIS Benchmarks** — отраслевые стандарты безопасности, ориентированные преимущественно на user-space и базовые настройки ОС. В сравнении с LKSPP являются более «лайтовым» вариантом.

**Kernel Lockdown** — модуль безопасности (LSM), ограничивающий доступ к функциям ядра, которые могут быть использованы для обхода Secure Boot или модификации образа работающего ядра (даже пользователем `root`).

**KSPP Reference Config** — эталонный набор опций конфигурации ядра (`.config`), рекомендуемый проектом LKSPP для максимальной защищённости. Включает: `CONFIG_HARDENED_USERCOPY=y`, `CONFIG_FORTIFY_SOURCE=y`, `CONFIG_DEBUG_SET_MODULE_RONX=y`, `CONFIG_SECURITY_DMESG_RESTRICT=y`, `CONFIG_DEFAULT_SECURITY_DAC=""` и др.

**Secure Boot** — стандарт UEFI, обеспечивающий проверку цифровой подписи загрузчика и ядра перед их выполнением. Является предварительным условием для автоматического включения режима `lockdown=confidentiality`.

**MOK (Machine Owner Key)** — механизм управления ключами Secure Boot в shim-загрузчике, позволяющий владельцу системы подписывать собственные модули ядра (например, драйверы NVIDIA, DKMS, ZFS) без пересборки shim.

## Основные концепции

### 1. Защита памяти и предотвращение эксплуатации

Современные ядра (6.x/7.0) включают механизмы для борьбы с Corruption-атаками:
*   **Memory Sanitization**: Очистка страниц при выделении или освобождении (`init_on_alloc=1`, `init_on_free=1`) предотвращает утечку данных через Use-After-Free.
*   **Shadow Stack (CET / Shadow Stack)**: Аппаратная поддержка предотвращения перезаписи адреса возврата в стеке (защита от ROP-цепочек). Требует CPU Intel Tiger Lake / AMD Zen 3+ и ядро 5.10+.
*   **SLAB_FREELIST_HARDENED**: Рандомизация и проверка целостности списков свободных блоков в аллокаторе памяти.
*   **STACKLEAK**: Очистка системного стека перед возвратом из системного вызова в пространство пользователя.
*   **HARDENED_USERCOPY**: Валидация границ при копировании данных между kernel/user space (защита от heap overflow через `copy_to_user`/`copy_from_user`). Включается через `CONFIG_HARDENED_USERCOPY=y`.
*   **FORTIFY_SOURCE**: Компиляторная защита строковых функций с проверкой границ буферов. В ядре включается через `CONFIG_FORTIFY_SOURCE=y`.
*   **REFCOUNT_FULL**: Переполнение/андерфлоу защита атомарных счётчиков ссылок (препятствует Use-After-Free через refcount манипуляции).
*   **KASLR / FG-KASLR**: Рандомизация адресного пространства ядра (подробнее: [KASLR](../KASLR.md)).
*   **KPTI**: Изоляция таблиц страниц пользователя и ядра (подробнее: [KPTI](../KPTI.md)).
*   **SMEP/SMAP**: Аппаратный запрет выполнения/доступа к user-space памяти из kernel-mode.
*   **PAGE_TABLE_ISOLATION**: Дополнительная изоляция для защиты от Meltdown/Spectre.

### 2. Режимы Kernel Lockdown

Активируется через параметр загрузки `lockdown=...` или при включенном Secure Boot:
*   **Integrity**: Блокирует прямую запись в `/dev/mem`, использование `kexec` неподписанных ядер, доступ к отладочным интерфейсам процессора (MSR).
*   **Confidentiality**: Включает `Integrity` + запрещает чтение памяти ядра (защита ключей и секретов).

### 3. Ограничение подсистем (Attack Surface Reduction)

*   **eBPF**: Из-за сложности и потенциальных JIT-уязвимостей доступ для непривилегированных пользователей должен быть закрыт (`kernel.unprivileged_bpf_disabled=1`).
*   **User Namespaces**: Несмотря на пользу для контейнеров, механизм часто используется в цепочках LPE-эксплуатации (через `unshare`). Ограничение через `user.max_user_namespaces=0`.
*   **Legacy Interfaces**: Отключение старых сетевых протоколов (DCCP, SCTP) и TTY-дисциплин.
*   **Module Signature Enforcement**: `modules_sig_enforce=1` требует подписи всех загружаемых модулей (требует инфраструктуру подписи).

### 4. Аппаратные механизмы изоляции

*   **SMEP (Supervisor Mode Execution Prevention)**: Аппаратный бит CR4, запрещающий выполнение кода из пользовательского пространства (Ring 3) при нахождении процессора в Ring 0 (kernel mode). Блокирует простые атаки ret2usr, когда эксплойт пытается передать управление на пользовательский шелл-код. Включается аппаратно, в ядре через `CONFIG_X86_SMEP=y`.
*   **SMAP (Supervisor Mode Access Prevention)**: Аналогично SMEP, но запрещает доступ (чтение/запись) к страницам пользовательского пространства из kernel mode. Требует явного использования `copy_to_user`/`copy_from_user` и инструкций `STAC`/`CLAC`. Включается через `CONFIG_X86_SMAP=y`. В сочетании с KPTI обеспечивает сильную изоляцию.
*   **CET (Control-flow Enforcement Technology)**: Аппаратный механизм Intel (поддерживается также AMD через альтернативные расширения), включающий Shadow Stack (защита адреса возврата в стеке от ROP-атак) и Indirect Branch Tracking (IBT, защита от Jump-Oriented Programming). Требует CPU Intel Tiger Lake+ / AMD Zen 3+ и ядра 5.10+ с `CONFIG_X86_CET=y`.
*   **IOMMU (Input-Output Memory Management Unit)**: Аппаратный блок (Intel VT-d / AMD-Vi), обеспечивающий изоляцию DMA-устройств. Включается параметрами загрузки `intel_iommu=on` или `amd_iommu=on`. Параметр `iommu=pt` (passthrough) сохраняет производительность, но включает проверку таблиц DMA. Защищает от атак через Thunderbolt, FireWire, PCIe устройства и malicious DMA.

### 5. Защита целостности кода и данных

*   **CFI (Control Flow Integrity)**: Механизм, обеспечивающий контроль целостности потока выполнения программы (в том числе ядра). В Linux реализован через `CONFIG_CFI_CLANG=y` (требует сборки ядра с Clang). Блокирует перезапись адресов возврата (ROP) и косвенных переходов (JOP) даже при наличии уязвимости memory corruption.
*   **RANDSTRUCT**: Рандомизация порядка полей и расположения структур ядра в памяти при каждой сборке. Включается через `CONFIG_RANDSTRUCT=y` (входит в LKSPP baseline). Усложняет exploitation, так как атакующий не может полагаться на фиксированные смещения в структурах (например, `task_struct`).
*   **STRICT_KERNEL_RWX / STRICT_MODULE_RWX**: Обеспечивает, чтобы страницы кода ядра и модулей были только для чтения/исполнения (RX), а данные — только для записи (RW), без промежуточных состояний (RWX). Включается через `CONFIG_STRICT_KERNEL_RWX=y` и `CONFIG_STRICT_MODULE_RWX=y` (в ядре 6.x включены по умолчанию в большинстве дистрибутивов).

## Побочные эффекты и риски (Breaking Changes)

Тонкая настройка безопасности может нарушить работу критической инфраструктуры:

| Параметр | Что может сломаться | Причина | Рекомендация по обходу |
| :--- | :--- | :--- | :--- |
| `kernel.kptr_restrict=2` | **Falco, Sysdig, perf, bcc** | Запрещает просмотр символов и адресов ядра, необходимых для профилирования и мониторинга. | На хостах с eBPF-мониторингом: `1` (требует `CAP_SYSLOG`) или исключить хост из hardening. |
| `kernel.unprivileged_bpf_disabled=1` | **Cilium, Falco, bpftrace, Tetragon** | Блокирует системный вызов `bpf` для пользователей без `CAP_SYS_ADMIN` или `CAP_BPF`. | Добавить `CAP_BPF`/`CAP_SYS_ADMIN` в контейнеры агентов или использовать `--privileged` для мониторинговых подов. |
| `user.max_user_namespaces=0` | **Rootless контейнеры (Docker rootless, Podman)** | Полностью блокирует возможность создания пользовательских пространств имен. | Не применять на хостах с rootless workloads. Использовать `user.max_user_namespaces=15000` (лимит). |
| `kernel.modules_disabled=1` | **Falco, драйверы GPU, ZFS, DKMS** | Запрещает загрузку любых LKM после инициализации системы. | Применять только на immutable-системах (Talos, Flatcar, Bottlerocket) после загрузки всех модулей. |
| `net.ipv4.conf.all.rp_filter=1` | **Calico, Cilium (CNI), WireGuard** | Фильтрация по обратному пути может блокировать легитимный трафик подов при сложной маршрутизации. | Установить `2` (loose mode) или настроить policy routing. |
| `net.ipv4.ip_forward=0` | **Любой CNI (кроме Cilium с eBPF), Docker, Kubernetes** | Нарушает маршрутизацию трафика между подами и внешним миром. | На контейнерных хостах: `1`. В `sysctl.d` использовать условное значение через Ansible facts. |
| `kernel.yama.ptrace_scope=2` | **gdb, strace, perf, debuggers** | Разрешает ptrace только для прямого родителя. | Для CI/debug-хостов: `1` (требует `CAP_SYS_PTRACE`) или `0`. |
| `kernel.perf_event_paranoid=3` | **perf, profilers, eBPF tools** | Полный запрет на performance monitoring для непривилегированных пользователей. | На серверах с APM: `2` (требует `CAP_PERFMON` с ядра 5.8+). |
| `lockdown=confidentiality` | **kexec, hibernation, модули без подписи, DKMS, модули NVIDIA** | Запрет на неавторизованную модификацию/чтение ядра. | Использовать `integrity` если Secure Boot не настроен; для NVIDIA — подписать модули MOK. |
| `spectre_v2=on l1tf=full,force mds=full,nosmt` | **Старые CPU (pre-2018), high-frequency trading** | Снижение производительности на 3–15% из-за отключения SMT и TLB flush. | На production 2024+ обычно безопасно; для legacy оставить `spectre_v2=on l1tf=off mds=off`. |
| `intel_iommu=on` / `amd_iommu=on` | **Устройства без DMA-масок, старые NIC** | Несовместимость с некоторыми PCIe устройствами, требующими прямого доступа. | Использовать `iommu=pt` или отключить для конкретных устройств через `iommu=noiommu`. |
| `kernel.stack_guard_gap=64` | **Некоторый код ядра, проверяющий границы стека вручную** | Может привести к панике при ручном управлении стеком. | Значение по умолчанию (64) безопасно; увеличивать только при наличии конкретной CVE. |
| `fs.protected_fifos=2` / `fs.protected_regular=2` | **Некоторые старые демоны, legacy-приложения** | Блокирует создание/следование по FIFO и regular файлам в липких директориях. | Обычно безопасно. При проблемах — `1` (предупреждение вместо блокировки). |

### Матрица совместимости: Workload vs Hardening Profile

| Профиль | Kubernetes Control Plane | Kubernetes Worker | Database (PostgreSQL/MySQL) | Web Server (nginx/Apache) | Monitoring (Prometheus/Grafana) | eBPF Observability (Falco/Cilium) | CI/CD Runners | Rootless Containers | Physical Server (SME/DB) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Maximum (Lockdown + All)** | ⚠️ Требует подписи модулей | ⚠️ Требует подписи модулей | ✅ | ✅ | ⚠️ `perf_event_paranoid=2` | ❌ | ❌ | ❌ | ✅ |
| **Hardened (LKSPP Baseline)** | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ `kptr_restrict=1`, `bpf_disabled=0` | ✅ | ⚠️ `userns_limit>0` | ✅ |
| **Balanced (CIS L1)** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Minimal (Defaults)** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

*Легенда: ✅ — совместимо, ⚠️ — требует тонкой настройки/исключений, ❌ — конфликтует.*

#### Примечания по новым параметрам

*   **Spectre / MDS / L1TF**: Параметры загрузки `spectre_v2=on`, `l1tf=full,force`, `mds=full,nosmt` снижают производительность на 3–15% на старых CPU (Intel pre-Ice Lake, AMD pre-Zen 2). На современных процессорах (2024+) влияние минимально.
*   **IOMMU**: `intel_iommu=on` / `amd_iommu=on` обязателен для серверов с прямым доступом к PCIe (SR-IOV, GPU passthrough, high-performance NICs). Для обычных рабочих нагрузок можно использовать `iommu=pt` (pass-through) для минимизации накладных расходов.
*   **CFI**: Доступно только при сборке ядра с Clang. На дистрибутивах с GCC-сборкой (RHEL, Debian stable) недоступно без кастомного ядра.

## Практические сценарии

### 1. Эталонная конфигурация sysctl (2026)

Создайте файл `/etc/sysctl.d/99-kernel-hardening.conf` для применения при загрузке:

```bash
# --- Защита от LPE и инспекции памяти ---
kernel.kptr_restrict = 2            # Скрыть адреса ядра в /proc/kallsyms
kernel.dmesg_restrict = 1           # Запрет чтения dmesg обычными пользователями
kernel.perf_event_paranoid = 3      # Максимальное ограничение подсистемы perf
kernel.yama.ptrace_scope = 2        # Разрешить ptrace только для дочерних процессов (или root)
kernel.unprivileged_bpf_disabled = 1 # Отключить eBPF для пользователей
net.core.bpf_jit_harden = 2         # Постоянная JIT-защита для всех процессов

# --- Защита адресного пространства (ASLR) ---
kernel.randomize_va_space = 2
vm.mmap_rnd_bits = 32               # Усиление рандомизации mmap (для x86_64)

# --- Ограничение User Namespaces (если не используются) ---
# kernel.unprivileged_userns_clone = 0 # Для Debian/Ubuntu
# user.max_user_namespaces = 0          # Для RHEL/Fedora и т.д.

# --- Защита от атак через файловые дескрипторы ---
fs.protected_fifos = 2
fs.protected_regular = 2
fs.protected_symlinks = 1
fs.protected_hardlinks = 1

# --- Дополнительные параметры (2026) ---
kernel.stack_guard_gap = 64         # Защита от переполнения стека ядра
```

### 2. Параметры загрузки ядра (GRUB)

Добавьте в `GRUB_CMDLINE_LINUX_DEFAULT`:
```text
lockdown=integrity slab_nomerge init_on_alloc=1 init_on_free=1 pti=on page_alloc.shuffle=1 spectre_v2=on l1tf=full,force mds=full,nosmt intel_iommu=on
```

> **Примечание:** `mds=full,nosmt` отключает Hyper-Threading на уязвимых CPU. На системах без MDS-уязвимостей (Intel Ice Lake+, AMD Zen 2+) можно использовать `mds=full` без `nosmt` для сохранения производительности.

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

### 4. Подпись модулей ядра и управление MOK

В системах с Secure Boot и Kernel Lockdown требуется подпись всех загружаемых модулей (включая out-of-tree: NVIDIA, ZFS, DKMS). Используется ключ MOK (Machine Owner Key) в shim-загрузчике.

```bash
# 1. Создание ключевой пары (выполняется 1 раз на систему)
openssl req -new -x509 -newkey rsa:2048 -keyout MOK.priv -outform DER -out MOK.der -nodes -days 36500 -subj "/CN=Custom Kernel Signing Key/"

# 2. Импорт ключа в shim (требует пароль при перезагрузке)
sudo mokutil --import MOK.der

# 3. После перезагрузки: выбрать "Enroll MOK" → "Continue" → "Yes" → ввести пароль

# 4. Подпись модуля
sudo /usr/src/linux-headers-$(uname -r)/scripts/sign-file sha256 MOK.priv MOK.der /path/to/module.ko

# 5. Проверка подписи
modinfo -F signature /path/to/module.ko
modinfo -F sig_key /path/to/module.ko
```

Для автоматизации в DKMS добавьте хук подписи:
```bash
# /etc/dkms/sign-modules.sh
#!/bin/bash
for mod in "$@"; do
    /usr/src/linux-headers-$(uname -r)/scripts/sign-file sha256 /etc/MOK.priv /etc/MOK.der "$mod"
done
```

### 5. Аудит событий ядра через auditd

Настройте аудит для отслеживания подозрительных операций в kernel-space:

```bash
# /etc/audit/rules.d/99-kernel-hardening.rules

# Доступ к физической памяти ядра
-a always,exit -F arch=b64 -S open -S openat -F path=/dev/mem -F perm=rwxa -k kernel_mem_access
-a always,exit -F arch=b64 -S open -S openat -F path=/dev/kmem -F perm=rwxa -k kernel_mem_access

# Загрузка/выгрузка модулей
-w /etc/modprobe.d/ -p wa -k modules_config
-a always,exit -F arch=b64 -S init_module -S finit_module -S delete_module -k module_load

# Изменение sysctl (как файлов, так и runtime)
-w /etc/sysctl.d/ -p wa -k sysctl_config
-w /proc/sys/ -p wa -k sysctl_runtime

# Попытки kexec
-a always,exit -F arch=b64 -S kexec_load -S kexec_file_load -k kexec_attempt

# Доступ к MSR (модельные специфичные регистры процессора)
-a always,exit -F arch=b64 -S rdmsr -S wrmsr -k msr_access

# Применение правил
augenrules --load
systemctl restart auditd
```

### 6. Автоматизация hardening через Ansible

Минимальный playbook для применения baseline (требует `community.general`):

```yaml
- name: Apply kernel hardening baseline
  hosts: all
  become: true
  tasks:
    - name: Deploy sysctl hardening
      copy:
        dest: /etc/sysctl.d/99-kernel-hardening.conf
        mode: '0644'
        content: |
          kernel.kptr_restrict = 2
          kernel.dmesg_restrict = 1
          kernel.perf_event_paranoid = 3
          kernel.yama.ptrace_scope = 2
          kernel.unprivileged_bpf_disabled = 1
          net.core.bpf_jit_harden = 2
          kernel.randomize_va_space = 2
          vm.mmap_rnd_bits = 32
          fs.protected_fifos = 2
          fs.protected_regular = 2
          fs.protected_symlinks = 1
          fs.protected_hardlinks = 1
      notify: reload sysctl

    - name: Blacklist dangerous modules
      copy:
        dest: /etc/modprobe.d/security-blacklist.conf
        mode: '0644'
        content: |
          install dccp /bin/true
          install sctp /bin/true
          install rds /bin/true
          install tipc /bin/true
          install firewire-core /bin/true
          install thunderbolt /bin/true

    - name: Harden GRUB cmdline
      lineinfile:
        path: /etc/default/grub
        regexp: '^GRUB_CMDLINE_LINUX_DEFAULT='
        line: 'GRUB_CMDLINE_LINUX_DEFAULT="quiet splash lockdown=integrity slab_nomerge init_on_alloc=1 init_on_free=1 pti=on page_alloc.shuffle=1 spectre_v2=on l1tf=full,force mds=full,nosmt intel_iommu=on"'
      notify: update grub

  handlers:
    - name: reload sysctl
      command: sysctl --system

    - name: update grub
      command: update-grub
      when: ansible_facts['os_family'] == "Debian"
```

### 7. Проверка hardening baseline (скрипт)

```bash
#!/usr/bin/env bash
set -euo pipefail

HARDENING_SCORE=0
MAX_SCORE=12

check() {
    local name="$1"
    local expected="$2"
    local actual
    actual=$(sysctl -n "$name" 2>/dev/null || echo "missing")
    if [ "$actual" = "$expected" ]; then
        echo "PASS $name=$actual"
        HARDENING_SCORE=$((HARDENING_SCORE + 1))
    else
        echo "FAIL $name: expected $expected, got $actual"
    fi
}

echo "=== Kernel Hardening Baseline Check ==="
check kernel.kptr_restrict 2
check kernel.dmesg_restrict 1
check kernel.perf_event_paranoid 3
check kernel.yama.ptrace_scope 2
check kernel.unprivileged_bpf_disabled 1
check net.core.bpf_jit_harden 2
check kernel.randomize_va_space 2
check fs.protected_fifos 2
check fs.protected_regular 2
check fs.protected_symlinks 1
check fs.protected_hardlinks 1

LOCKDOWN=$(cat /sys/kernel/security/lockdown 2>/dev/null || echo "none")
if [[ "$LOCKDOWN" =~ \[(integrity|confidentiality)\] ]]; then
    echo "PASS lockdown=$LOCKDOWN"
    HARDENING_SCORE=$((HARDENING_SCORE + 1))
else
    echo "FAIL lockdown: expected [integrity] or [confidentiality], got $LOCKDOWN"
fi

if bootctl status | grep -q "Secure Boot: enabled"; then
    echo "PASS Secure Boot enabled"
    HARDENING_SCORE=$((HARDENING_SCORE + 1))
else
    echo "FAIL Secure Boot not enabled"
fi

echo "=== Score: $HARDENING_SCORE / $MAX_SCORE ==="
if [ $((MAX_SCORE - HARDENING_SCORE)) -gt 2 ]; then
    exit 1
fi
```

### 8. Валидация, откат и Troubleshooting

#### Валидация после применения

```bash
# Применение sysctl
sudo sysctl --system

# Проверка ключевых параметров
sudo sysctl -a | grep -E "kptr_restrict|dmesg_restrict|unprivileged_bpf|ptrace_scope|perf_event_paranoid"

# Проверка режима lockdown
cat /sys/kernel/security/lockdown
# → none [integrity] confidentiality

# Проверка Secure Boot
bootctl status | grep -i secure
# → Secure Boot: enabled

# Проверка загруженных LSM
cat /sys/kernel/security/lsm
# → capability selinux yama lockdown ...

# Проверка KASLR
sudo dmesg | grep -i "kernel: .*offset"
# → Linux version 6.x ... (randomized: offset=0x...)
```

#### Rollback

```bash
# Восстановление sysctl из бэкапа
sudo cp /etc/sysctl.d/99-kernel-hardening.conf.bak /etc/sysctl.d/99-kernel-hardening.conf
sudo sysctl --system

# Восстановление GRUB
sudo cp /etc/default/grub.bak /etc/default/grub
sudo update-grub

# Отключение lockdown (если критично)
sudo sed -i 's/lockdown=integrity//g' /etc/default/grub
sudo update-grub
```

#### Типичные проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Черный экран после включения Secure Boot | Нет подписи shim/GRUB/ядра | Проверить `bootctl status`, загрузиться в legacy boot, подписать все артефакты |
| `modprobe: ERROR: could not insert` | Lockdown или неподписанный модуль | Подписать модуль через MOK или отключить `lockdown=integrity` (не рекомендуется для production) |
| Низкая производительность после KPTI | Устаревший CPU без PCID | Обновить микрокод BIOS/UEFI; для тестовых сред можно добавить `nopti` (категорически не рекомендуется в production) |
| eBPF-инструменты не работают | `kernel.unprivileged_bpf_disabled=1` | Добавить `CAP_BPF` (ядро 5.8+) или `CAP_SYS_ADMIN` в контейнеры агентов; на хостах с мониторингом можно установить `0` |
| Panic при загрузке с `nosmt=1` | Поврежденный микрокод или legacy BIOS | Удалить параметр, обновить прошивку; `nosmt=1` обязателен только для систем с чувствительными данными и Spectre/MDS уязвимостями |

## SCA: Проверка харденинга в Wazuh

SCA-политика для автоматизированного контроля параметров ядра. Подробнее о работе модуля: **[Оценка конфигурации безопасности (SCA) в Wazuh](../../../../Security/Tools/Wazuh/wazuh-sca.md)**.

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
  - id: 100006
    title: "Secure Boot should be enabled"
    rules:
      - 'f:/sys/firmware/efi/efivars/SecureBoot-* -> r:1'
  - id: 100007
    title: "Stack guard gap should be 64"
    rules:
      - 'f:/proc/sys/kernel/stack_guard_gap -> 64'
  - id: 100008
    title: "Protected symlinks and hardlinks should be 1"
    rules:
      - 'f:/proc/sys/fs/protected_symlinks -> 1'
      - 'f:/proc/sys/fs/protected_hardlinks -> 1'
```

## Дополнительная информация

### Инструменты аудита
*   **kernel-hardening-checker**: Скрипт для проверки конфигурации ядра и параметров загрузки на соответствие рекомендациям KSPP.
*   **[Lynis](../../../../Security/Tools/lynis.md)**: Проводит комплексный аудит безопасности системы, включая параметры ядра.
*   **Скрипт проверки baseline**: См. раздел «Проверка hardening baseline» выше для готового bash-скрипта, который можно интегрировать в CI/CD.

### См. также
- [KASLR (Kernel Address Space Layout Randomization)](../KASLR.md)
- [KPTI (Kernel Page Table Isolation)](../KPTI.md)
- [Linux Capabilities](../Capabilities.md)
- [auditd: аудит системных вызовов](../../../../SystemAdministration/Logging/auditd.md)
- [Мониторинг ядра через Wazuh](../../../../Security/Tools/Wazuh/kernel_monitoring.md)
