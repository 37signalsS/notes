# KASLR (Kernel Address Space Layout Randomization)

## Определения и терминология

**KASLR (Kernel Address Space Layout Randomization)** — механизм безопасности ядра Linux, который при каждой загрузке системы случайным образом изменяет базовый адрес расположения кода ядра, его модулей и ключевых структур данных в виртуальной памяти.

**Цель:** защита от эксплуатации уязвимостей типа **ROP (Return-Oriented Programming)** и переполнения буфера в пространстве ядра. Путем рандомизации адресов KASLR лишает атакующего возможности заранее знать точное расположение функций (например, `commit_creds`), что делает написание надежного эксплойта значительно более сложной задачей.

**Early KASLR** — режим, при котором смещение вычисляется в самом начале загрузки, ещё до распаковки ядра, что защищает код от утечек на этапе инициализации.

**CONFIG_RANDOMIZE_BASE** — параметр конфигурации ядра, включающий KASLR. В современных дистрибутивах обычно включён по умолчанию.

## Основные концепции

### Связь с ASLR

KASLR является расширением механизма **ASLR (Address Space Layout Randomization)**, применяемого к пользовательским процессам:

| Характеристика | ASLR | KASLR |
| :--- | :--- | :--- |
| **Уровень** | Пространство пользователя (Userspace) | Пространство ядра (Kernelspace) |
| **Что рандомизирует** | Стек, куча, библиотеки (`libc`), код процесса | Код ядра, модули, таблицы страниц |
| **Время смены адресов** | При каждом запуске процесса | При каждой загрузке ОС |

Подробнее об ASLR: [Защита памяти ядра и процессов](../Fstec/kernel_runtime_protection.md).

### Принцип работы и источники энтропии

Процесс рандомизации зависит от качества случайных данных, доступных на ранних этапах загрузки:

1.  **Источники энтропии:**
    - **Аппаратные генераторы (hRNG):** Инструкции процессора (например, `RDRAND` на x86, `RNDR` на ARM).
    - **Загрузчик (Bootloader):** Современные загрузчики (GRUB, systemd-boot) через UEFI `EFI_RNG_PROTOCOL` могут передавать ядру случайные семена (seeds).
    - **Джиттер:** Использование временных задержек между прерываниями на ранних стадиях.
    - **Физическая память:** Карта памяти (E820/EFFI) и размер RAM добавляют уникальности смещению.
2.  **Вычисление смещения (Offset):** На основе полученных данных вычисляется 64-битное (для x64) смещение.
3.  **Загрузка и релокация:** Ядро распаковывается и загружается по адресу `физический_базовый_адрес + смещение`. Таблицы переадресации корректируются под новый адрес.
4.  **Ранняя рандомизация (Early KASLR):** В ядрах 4.18+ смещение может быть выбрано ещё до распаковки `vmlinux`, что исключает окно утечки адресов на этапе decompressor.

### Архитектурные особенности (2025–2026)

- **x86_64:** Наиболее зрелая реализация. Рандомизирует как физический, так и виртуальный адрес. Поддерживает 5-level paging (LA57) для расширения адресного пространства. На современных CPU (Intel Ice Lake+, AMD Zen 2+) применяется совместно с PCID/INVPCID для снижения накладных расходов.
- **ARM64:** Включает рандомизацию «линейного отображения» (linear mapping), хотя она часто слабее основной рандомизации кода. Поддержка стабильна в ядрах 5.10+. На устройствах с UEFI seed поддержка энтропии выше.
- **RISC-V:** Поддержка KASLR была стабилизирована в 2025 году, обеспечивая паритет с основными архитектурами. Требует включения `CONFIG_RANDOMIZE_BASE` и источника энтропии (RDRAND или bootloader seed).
- **ppc64le:** Поддерживается через `CONFIG_RANDOMIZE_BASE`, но имеет особенности из-за большого размера ядра и ограниченного диапазона виртуальных адресов.

### FG-KASLR (Function Granular KASLR)

**FG-KASLR** — это «тонкозернистая» рандомизация, которая перемещает каждую функцию ядра отдельно, а не всё ядро целиком.
- **Статус (2026):** **Не принят в основную ветку ядра (upstream).**
- **Причины:** Высокая сложность поддержки, деградация производительности (до 5–10% из-за промахов кэша инструкций) и ограниченная эффективность против утечек данных.
- **Альтернатива:** Сообщество сфокусировалось на **FineIBT** и **KCFI** (Control-Flow Integrity).

## Ограничения и векторы атак

KASLR не является абсолютной защитой и рассматривается как «усложняющий фактор», а не непреодолимый барьер.

### Методы обхода (Bypass)

1.  **Information Leak (Утечка информации):** Самый распространенный метод. Любая уязвимость чтения памяти (например, чтение неинициализированного стека) позволяет атакующему узнать указатель на функцию и вычислить базовое смещение.
2.  **Side-Channel (Побочные каналы):**
    - **EntryBleed:** Использование инструкции `prefetch` для измерения времени доступа к кэшу TLB, что позволяет определить адреса обработчиков системных вызовов даже при включенном KPTI.
    - **Branch Target Buffer (BTB):** Атаки типа Spectre могут быть использованы для косвенного определения адресов.
    - **TSX Asynchronous Abort (TAA) / ZombieLoad / RIDL:** Уязвимости в Transactional Synchronization Extensions и других механизмах speculative execution позволяют читать данные из буферов CPU, потенциально leaking kernel pointers.
3.  **Physical probing / DMA:** При наличии физического доступа к шине (Thunderbolt, PCIe) атакующий может читать память напрямую, минуя виртуальную адресацию. Здесь помогает IOMMU.
4.  **Data-Only Attacks:** Трендовый вектор 2026 года. Вместо захвата потока выполнения (где важны адреса кода), атакующие манипулируют структурами данных (например, `cred` процесса) напрямую, используя другие примитивы.
5.  **Rowhammer + KASLR:** Сочетание атак на целостность DRAM с утечкой информации может использоваться для модификации структур ядра без точного знания адресов кода.

### Взаимодействие с другими механизмами

Эффективность KASLR многократно возрастает при совместном использовании с:
- **KPTI (Kernel Page Table Isolation):** Скрывает таблицы страниц ядра от пользователей, затрудняя утечки через побочные каналы.
- **SMEP / SMAP:** Запрещают исполнение/доступ к памяти пользователя из ядра, предотвращая простые `ret2usr` атаки.
- **FineIBT / KCFI:** Обеспечивают целостность потока управления, делая знание адресов бесполезным для построения ROP-цепочек.
- **CR4 Pinning:** «Защита от записи» критических битов регистра CR4, предотвращающая программное отключение SMEP/SMAP через эксплойты.
- **IOMMU (Intel VT-d / AMD-Vi):** Изолирует DMA-устройства, защищая от физических векторов утечек через шину.
- **Kernel Lockdown:** Ограничивает доступ к `/dev/mem`, `kexec` и MSR, уменьшая возможность разведки.

## Практические сценарии

### 1. Проверка статуса KASLR

**Способ 1: Анализ dmesg (рекомендуемый)**

```bash
sudo dmesg | grep -i "Kernel Offset"
# → [    0.000000] Kernel Offset: 0x22000000 from 0xffffffff81000000 (relocation range: 0xffffffff80000000-0xffffffffbfffffff)
```
Если смещение (Offset) отлично от `0x0`, KASLR активен.

**Способ 2: Анализ ранних сообщений ядра**

```bash
# Для ядер 4.18+ с early KASLR
sudo dmesg -T | grep -i "randomize"
# → [Thu Jan 1 00:00:00 1970] Kernel randomize KASLR: enabled
```

**Способ 3: Проверка параметров загрузки**

```bash
cat /proc/cmdline | grep -E "kaslr|nokaslr"
# Если параметр отсутствует — используется значение по умолчанию (обычно включено)
# nokaslr — явное отключение
```

**Способ 4: Сравнение адресов символов**

```bash
# 1. Запомнить адрес
sudo grep " T _stext" /proc/kallsyms

# 2. Перезагрузка.

# 3. Повторная проверка. Изменение адреса подтверждает работу KASLR.
```

**Способ 5: Проверка через sysfs (если доступно)**

```bash
# На некоторых архитектурах/дистрибутивах
cat /sys/kernel/randomize_kstack_offset 2>/dev/null || echo "not available"
# → 1 (per-task stack randomization enabled)
```

### 2. Управление KASLR

Настройка производится через параметры командной строки ядра в `/etc/default/grub` (переменная `GRUB_CMDLINE_LINUX_DEFAULT`).

| Параметр | Описание |
| :--- | :--- |
| `kaslr` | Явное включение (обычно включено по умолчанию в современных дистрибутивах). |
| `nokaslr` | Полное отключение рандомизации. |
| `randomize_kstack_offset=1` | Включает per-task рандомизацию смещения стека ядра (ядро 5.8+). |
| `randomize_vdso=1` | Принудительная рандомизация адреса VDSO (если не включено по умолчанию). |

**Когда стоит отключать (`nokaslr`):**
- **Отладка ядра:** Для использования отладчиков (KGDB) и анализа дампов памяти (Crash).
- **Гибернация:** В некоторых старых конфигурациях KASLR препятствует корректному восстановлению из файла подкачки (Suspend-to-Disk).
- **Производительность:** В специфических Real-time системах, где критична предсказуемость таймингов (крайне редкий случай).
- **kexec:** Некоторые старые реализации kexec требуют фиксированного адреса ядра.

### 3. Взаимодействие с kexec и живым обновлением

**kexec** требует, чтобы новое ядро было загружено по корректному адресу. При включенном KASLR:
- `kexec -l` автоматически использует текущую командную строку, включая параметры KASLR.
- Если `nokaslr` был указан при загрузке текущего ядра, kexec сохранит это поведение.
- **Kexec Handover (KHO)** в ядрах 6.16+ поддерживает передачу состояния между ядрами с разными смещениями KASLR.

**Live Patching** (kpatch, kgraft, Canonical Livepatch):
- Патчи применяются к уже загруженному ядру с фиксированным адресом. KASLR не мешает работе live patch, так как модуль патча связывается через `ftrace` по символам, а не по абсолютным адресам.
- Однако при отладке live patch важно учитывать смещение KASLR при анализе дампов.

### 4. Аудит событий KASLR через auditd

Настройте аудит для отслеживания попыток обхода KASLR:

```bash
# /etc/audit/rules.d/99-kaslr-audit.rules

# Попытки доступа к физической памяти (прямое чтение адресов)
-a always,exit -F arch=b64 -S open -S openat -F path=/dev/mem -F perm=rwxa -k kaslr_phys_mem

# Чтение MSR (модельные регистры, могут использоваться для определения физических адресов)
-a always,exit -F arch=b64 -S rdmsr -S wrmsr -k kaslr_msr

# Загрузка неподписанных модулей (попытка внедрения кода)
-a always,exit -F arch=b64 -S init_module -S finit_module -S delete_module -k kaslr_module

# Изменение параметров загрузки/ядро
-w /etc/default/grub -p wa -k kaslr_grub
-w /boot/ -p wa -k kaslr_boot

# Применение правил
augenrules --load
systemctl restart auditd
```

### 5. Автоматизация проверки KASLR через Ansible

```yaml
- name: Audit KASLR status across fleet
  hosts: all
  become: true
  gather_facts: true
  tasks:
    - name: Check kernel offset in dmesg
      ansible.builtin.shell: dmesg | grep -i "Kernel Offset" || echo "not found"
      register: kaslr_offset
      changed_when: false

    - name: Check cmdline for nokaslr
      ansible.builtin.shell: cat /proc/cmdline | grep -o 'nokaslr' || echo "kaslr likely enabled"
      register: kaslr_cmdline
      changed_when: false

    - name: Check randomize_kstack_offset
      ansible.builtin.shell: cat /proc/sys/kernel/randomize_kstack_offset 2>/dev/null || echo "not available"
      register: kstack_offset
      changed_when: false

    - name: Output summary
      ansible.builtin.debug:
        msg:
          - "Host: {{ inventory_hostname }}"
          - "KASLR offset: {{ kaslr_offset.stdout }}"
          - "Cmdline: {{ kaslr_cmdline.stdout }}"
          - "Stack offset: {{ kstack_offset.stdout }}"
```

### 6. Проверка hardening baseline (скрипт)

```bash
#!/usr/bin/env bash
set -euo pipefail

HARDENING_SCORE=0
MAX_SCORE=14

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

echo "=== Kernel Hardening + KASLR Baseline Check ==="

# KASLR specific checks
if sudo dmesg | grep -qi "Kernel Offset: 0x0"; then
    echo "FAIL KASLR offset appears to be 0x0"
else
    echo "PASS KASLR offset is non-zero"
    HARDENING_SCORE=$((HARDENING_SCORE + 1))
fi

if cat /proc/cmdline | grep -q "nokaslr"; then
    echo "FAIL nokaslr present in cmdline"
else
    echo "PASS nokaslr not present"
    HARDENING_SCORE=$((HARDENING_SCORE + 1))
fi

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

echo "=== Score: $HARDENING_SCORE / $MAX_SCORE ==="
if [ $((MAX_SCORE - HARDENING_SCORE)) -gt 3 ]; then
    exit 1
fi
```

### 7. Валидация, откат и Troubleshooting

#### Валидация после применения

```bash
# Проверка параметров загрузки
cat /proc/cmdline | grep -E "kaslr|nokaslr|randomize"

# Проверка смещения KASLR
sudo dmesg | grep -i "Kernel Offset"

# Проверка per-task stack randomization
cat /proc/sys/kernel/randomize_kstack_offset 2>/dev/null || echo "not available"

# Проверка lockdown (влияет на kexec и модули)
cat /sys/kernel/security/lockdown

# Проверка Secure Boot
bootctl status | grep -i secure

# Проверка загруженных LSM
cat /sys/kernel/security/lsm
```

#### Rollback

```bash
# Отключение KASLR через GRUB
sudo sed -i 's/GRUB_CMDLINE_LINUX_DEFAULT="/&nokaslr /g' /etc/default/grub
sudo update-grub

# Или полностью очистить параметры
sudo sed -i 's/ kaslr//g; s/ nokaslr//g' /etc/default/grub
sudo update-grub

# Откат sysctl
sudo cp /etc/sysctl.d/99-kernel-hardening.conf.bak /etc/sysctl.d/99-kernel-hardening.conf
sudo sysctl --system
```

#### Типичные проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| KASLR смещение = 0x0 | `nokaslr` в cmdline, устаревший GRUB или нет энтропии | Убрать `nokaslr`, обновить GRUB, добавить `random.trust_cpu=on` если CPU имеет RDRAND |
| kexec не работает после включения KASLR | Старый kexec-tools без поддержки relocated kernels | Обновить `kexec-tools` до 2.0.20+ или отключить KASLR |
| Panic при загрузке с `randomize_kstack_offset=1` | Устаревший драйвер, нарушающий assumptions о стеке | Убрать параметр или обновить драйвер |
| Низкая производительность на старых CPU | KASLR + отсутствие PCID + Spectre/MDS mitigations | Обновить микрокод, рассмотреть `nokaslr` только для изолированных тестовых сред |
| Отладочные дампы (kdump) неверны | KASLR сбивает адреса в vmcore | Использовать `crash` с правильным `vmlinux` и опцией `--kaslr` |

### 8. Специфичные параметры hardening и KASLR

В контексте KASLR важны следующие параметры загрузки и sysctl, которые усиливают защиту адресного пространства:

**GRUB cmdline (дополнение к базовому hardening):**
```text
lockdown=integrity slab_nomerge init_on_alloc=1 init_on_free=1 pti=on page_alloc.shuffle=1 spectre_v2=on l1tf=full,force mds=full,nosmt intel_iommu=on randomize_kstack_offset=1
```

**sysctl параметры:**
```bash
# /etc/sysctl.d/99-kernel-hardening.conf

kernel.kptr_restrict = 2
kernel.dmesg_restrict = 1
kernel.perf_event_paranoid = 3
kernel.yama.ptrace_scope = 2
kernel.unprivileged_bpf_disabled = 1
net.core.bpf_jit_harden = 2
kernel.randomize_va_space = 2
vm.mmap_rnd_bits = 32
kernel.stack_guard_gap = 64
fs.protected_fifos = 2
fs.protected_regular = 2
fs.protected_symlinks = 1
fs.protected_hardlinks = 1
```

## SCA: Проверка KASLR в Wazuh

SCA-политика для автоматизированного контроля параметров ядра. Подробнее о работе модуля: **[Оценка конфигурации безопасности (SCA) в Wazuh](../../../Security/Tools/Wazuh/wazuh-sca.md)**.

**Файл:** `/var/ossec/etc/custom_scripts/sca_kaslr.yml`

```yaml
policy:
  id: "kaslr_hardening"
  file: "kaslr.yml"
  name: "KASLR and Kernel Randomization Compliance"
  description: "Checks KASLR status, boot parameters, and randomization settings"
  regex_type: "pcre2"

requirements:
  title: "Check that the target is a Linux system"
  condition: all
  rules:
    - 'f:/proc/sys/kernel/ostype -> r:Linux'

checks:
  - id: 200001
    title: "KASLR should not be disabled"
    rules:
      - 'f:/proc/cmdline -> r:^((?!nokaslr).)*$'
  - id: 200002
    title: "kernel.randomize_va_space should be 2"
    rules:
      - 'f:/proc/sys/kernel/randomize_va_space -> 2'
  - id: 200003
    title: "vm.mmap_rnd_bits should be 32"
    rules:
      - 'f:/proc/sys/vm/mmap_rnd_bits -> 32'
  - id: 200004
    title: "Kernel offset should be non-zero"
    rules:
      - 'f:/proc/kallsyms -> r:^([0-9a-f]+) T _stext$'
  - id: 200005
    title: "Stack guard gap should be 64"
    rules:
      - 'f:/proc/sys/kernel/stack_guard_gap -> 64'
```

## Дополнительная информация

### KASLR и гибернация

Существует конфликт между KASLR и гибернацией: для восстановления ядро должно загрузиться по тем же адресам. В современных дистрибутивах это решается либо автоматическим отключением KASLR при наличии раздела подкачки для гибернации, либо сохранением метаданных смещения в образе восстановления.

### KASLR в контейнерах и виртуализации

- **Контейнеры (Docker, Podman):** KASLR работает на уровне хоста. Внутри контейнера `/proc/kallsyms` показывает адреса хостового ядра с применённым KASLR. Контейнеры не могут independently управлять KASLR.
- **Виртуальные машины (KVM/QEMU):** Гостевая ОС имеет свой экземпляр KASLR. Вложенная виртуализация (Nested Virtualization) может требовать дополнительных параметров (например, `nested=1` + `ept=1`).
- **SR-IOV / GPU Passthrough:** При прямом доступе к PCIe устройствам важен IOMMU (`intel_iommu=on` / `amd_iommu=on`), который дополняет KASLR, защищая от DMA-атак через физические адреса.

### Матрица совместимости: KASLR и Workload

| Профиль | Kubernetes Control Plane | Kubernetes Worker | Database (PostgreSQL/MySQL) | Web Server (nginx/Apache) | Monitoring (Prometheus/Grafana) | eBPF Observability (Falco/Cilium) | CI/CD Runners | Rootless Containers | Physical Server (SME/DB) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Maximum (Lockdown + All)** | [OK] | [OK] | [OK] | [OK] | [!] perf_event_paranoid=2 | [BLOCKED] | [BLOCKED] | [BLOCKED] | [OK] |
| **Hardened (LKSPP Baseline)** | [OK] | [OK] | [OK] | [OK] | [OK] | [!] kptr_restrict=1 | [OK] | [!] userns_limit>0 | [OK] |
| **Balanced (CIS L1)** | [OK] | [OK] | [OK] | [OK] | [OK] | [OK] | [OK] | [OK] | [OK] |
| **Minimal (Defaults)** | [OK] | [OK] | [OK] | [OK] | [OK] | [OK] | [OK] | [OK] | [OK] |

*Легенда: [OK] — совместимо, [!] — требует тонкой настройки/исключений, [BLOCKED] — конфликтует.*

### См. также
- [Харденинг ядра Linux](../../Security/Mechanisms/Kernel/hardening.md)
- [Изоляция таблиц страниц (KPTI)](./KPTI.md)
- [Безопасность модулей ядра](./kernel_module_security.md) — подпись и контроль загрузки модулей
- [Механизм ASLR для приложений](../Fstec/kernel_runtime_protection.md)
- [Живое обновление ядра: Live Patching и kexec](../../Core/kernel/live_patching.md)
- [Загрузчик GRUB](../../SystemAdministration/grub.md)
- [Мониторинг ядра через Wazuh](../../../Security/Tools/Wazuh/kernel_monitoring.md)
