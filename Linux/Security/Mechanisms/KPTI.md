# KPTI (Kernel Page Table Isolation)

## Определения

**KPTI (Kernel Page Table Isolation)** — механизм безопасности ядра Linux, предназначенный для защиты от аппаратной уязвимости **Meltdown** (CVE-2017-5754). Основная задача KPTI — предотвратить возможность чтения памяти ядра из пользовательского пространства через спекулятивное выполнение инструкций на уязвимых процессорах.

**Принцип:** До внедрения KPTI (ранее известного как KAISER) ядро Linux использовало общие таблицы страниц для пространства пользователя и ядра в целях ускорения переключения контекста. KPTI разделяет эти таблицы на два набора, оставляя в «пользовательской» версии лишь минимально необходимый набор адресов ядра для обеспечения входа в систему и обработки прерываний.

## Основные концепции

### Изоляция адресного пространства

1.  **Двойные таблицы страниц:** Для каждого процесса создается два набора таблиц страниц:
    - **Kernel-space tables:** Полный доступ к памяти ядра и процесса. Используется только когда процессор работает в режиме ядра (CPL 0).
    - **User-space tables:** Содержат маппинг памяти пользователя и крайне ограниченную область ядра (трамплины для системных вызовов, векторы прерываний).
2.  **Механизм переключения:** При каждом переходе `user -> kernel` (системный вызов, прерывание) ядро переключает регистр управления таблицами страниц (например, `CR3` на архитектуре x86) на «полные» таблицы. При возврате в `user-space` происходит обратное переключение.
3.  **Аппаратная поддержка (PCID/INVPCID):**
    - Основной недостаток KPTI — деградация производительности из-за сброса **TLB (Translation Lookaside Buffer)** при смене `CR3`.
    - **PCID (Process-Context Identifiers):** Позволяет помечать записи в TLB идентификатором контекста. Это позволяет ядру переключать таблицы страниц без полной очистки TLB, что снижает накладные расходы с ~30% до менее чем 5% на большинстве нагрузок.
    - **INVPCID:** Инструкция для селективной инвалидации записей TLB по PCID, дополнительно улучшающая производительность.

### Взаимодействие с KASLR

KPTI значительно усиливает эффективность [KASLR](./KASLR.md):
- **Скрытие маппинга:** KPTI делает страницы ядра невидимыми (отсутствующими в таблицах) для кода пользователя, что предотвращает утечку адресов через многие побочные каналы.
- **EntryBleed:** Атака, позволяющая вычислить смещение KASLR даже при включенном KPTI, используя задержки инструкции `prefetch` при обращении к точкам входа в ядро (которые обязаны оставаться маппированными в пользовательских таблицах).

### Статус на современных процессорах (2025–2026)

На современном оборудовании KPTI часто **отключен по умолчанию**, так как уязвимость Meltdown была исправлена на аппаратном уровне:
*   **Intel:** Начиная с 9-го поколения (Coffee Lake Refresh) и новее (Alder/Raptor/Arrow Lake), процессоры имеют аппаратную защиту. Ядро определяет флаг `rdcl_no` и автоматически отключает KPTI.
*   **AMD:** Процессоры AMD (включая Zen 5) архитектурно не подвержены Meltdown, поэтому KPTI на них не используется по умолчанию.
*   **Apple Silicon (ARM):** Процессоры M1/M2/M3/M4 имеют встроенную изоляцию и не требуют KPTI.
*   **ARM64 (общий случай):** Начиная с ядра 5.10+, KPTI включен только на уязвимых ядрах (Cortex-A75, A76 и др. до патчей). Проверяется через флаг `kpti=on` в `/proc/cpuinfo` или `dmesg`.

## Практические сценарии

### 1. Проверка статуса защиты

**Метод 1: Проверка через sysfs (Рекомендуемый)**
Это наиболее надежный способ узнать текущий статус защиты и используемые методы исправления.
```bash
cat /sys/devices/system/cpu/vulnerabilities/meltdown
# Возможные выводы:
# → Mitigation: PTI (Механизм включен и работает)
# → Not affected (Процессор не подвержен уязвимости, KPTI выключен)
# → Vulnerable (Система уязвима, защита неактивна)

# Проверка всех уязвимостей сразу
grep . /sys/devices/system/cpu/vulnerabilities/*
```

**Метод 2: Проверка через dmesg**
```bash
dmesg | grep -i "Kernel/User page tables isolation"
# → [    0.000000] Kernel/User page tables isolation: enabled
# → [    0.000000] Kernel/User page tables isolation: disabled (hardware mitigation)
```

**Метод 3: Проверка через /proc/cpuinfo (флаги CPU)**
```bash
# На Intel: наличие флага 'rdcl_no' означает аппаратную защиту (KPTI не нужен)
grep -m1 '^flags' /proc/cpuinfo | grep -o '\brdcl_no\b'

# На ARM64: проверка KPTI статуса
grep -i kpti /proc/cpuinfo
```

**Метод 4: Проверка конфигурации ядра**
```bash
# Проверить, скомпилирован ли KPTI в ядро
grep CONFIG_PAGE_TABLE_ISOLATION /boot/config-$(uname -r)
# → CONFIG_PAGE_TABLE_ISOLATION=y (встроен)
# → CONFIG_PAGE_TABLE_ISOLATION=m (модуль, редко)
# → # CONFIG_PAGE_TABLE_ISOLATION is not set (отключен при сборке)

# Проверить параметры командной строки ядра
cat /proc/cmdline | grep -o 'pti=[^ ]*'
```

### 2. Управление через параметры загрузки

Управление осуществляется через параметры командной строки ядра (GRUB).

| Параметр | Описание |
| :--- | :--- |
| `pti=on` | Принудительное включение KPTI. Может использоваться для параноидальной защиты KASLR. |
| `pti=off` / `nopti` | Принудительное отключение. Используется для возврата производительности на старых CPU. |
| `pti=auto` | Автоматический выбор на основе характеристик CPU (по умолчанию). |
| `mitigations=off` | Отключает все программные исправления (включая KPTI, Retpoline и др.). Не рекомендуется для систем с выходом в сеть. |

**Пример настройки через GRUB (Debian/Ubuntu/RHEL/Fedora):**
```bash
# 1. Редактирование конфигурации GRUB
vim /etc/default/grub

# 2. Добавление параметра в GRUB_CMDLINE_LINUX_DEFAULT
GRUB_CMDLINE_LINUX_DEFAULT="quiet pti=on"
# или для принудительного отключения:
# GRUB_CMDLINE_LINUX_DEFAULT="quiet pti=off"

# 3. Обновление конфигурации загрузчика
# Debian/Ubuntu:
update-grub
# RHEL/Fedora/CentOS:
grub2-mkconfig -o /boot/grub2/grub.cfg
# или для UEFI:
grub2-mkconfig -o /boot/efi/EFI/redhat/grub.cfg

# 4. Перезагрузка
reboot
```

**Временное изменение (до перезагрузки) — невозможно.** KPTI требует перезагрузки, так как меняет структуру таблиц страниц при ранней инициализации ядра.

### 3. Оценка влияния на производительность

#### Бенчмаркинг системных вызовов
```bash
# Установка утилит (Debian/Ubuntu)
apt-get install -y lmbench perf

# Простой теск системных вызовов (getpid в цикле)
# Запуск без KPTI (pti=off) и с KPTI (pti=on) для сравнения
lmbench-bw-proc -N 1000000 /tmp/test

# Использование perf для анализа TLB misses
perf stat -e dTLB-load-misses,dTLB-loads,cycles,instructions -a sleep 10

# Специфичные метрики KPTI (kernel/user transitions)
perf stat -e context-switches,cpu-migrations,page-faults -a sleep 10
```

#### Мониторинг накладных расходов в продакшене
```bash
# Проверка частоты переключений контекста (высокие значения могут указывать на накладные расходы KPTI)
watch -n 1 'cat /proc/stat | grep ctxt'

# Анализ задержек системных вызовов через bpftrace (требует ядро 4.9+)
bpftrace -e 'tracepoint:syscalls:sys_enter_* { @start[tid] = nsecs; } tracepoint:syscalls:sys_exit_* /@start[tid]/ { @latency[probe] = hist(nsecs - @start[tid]); delete(@start[tid]); }'

# Использование pidstat для отслеживания системных вызовов на процесс
pidstat -w 1  # volontary/non-volontary context switches per second
```

#### Типичные накладные расходы (ориентировочные):
| Нагрузка | Без PCID | С PCID |
| :--- | :--- | :--- |
| Syscall-heavy (redis, nginx, DB) | 10–30% | 2–5% |
| Compute-heavy (расчёты, рендеринг) | <1% | <1% |
| I/O-heavy (файловые серверы) | 5–15% | 1–3% |

### 4. Автоматизация проверки и аудита

#### Скрипт для сбора отчёта о статусе KPTI
```bash
#!/bin/bash
# kpti-status.sh — сбор информации о статусе KPTI
# Использование: ./kpti-status.sh

set -euo pipefail

echo "=== KPTI Status Report ==="
echo "Date: $(date)"
echo "Host: $(hostname)"
echo "Kernel: $(uname -r)"
echo

echo "--- CPU Vulnerabilities ---"
if [[ -d /sys/devices/system/cpu/vulnerabilities ]]; then
    grep -H . /sys/devices/system/cpu/vulnerabilities/* 2>/dev/null | column -t -s:
else
    echo "sysfs vulnerabilities not available (kernel < 4.14?)"
fi
echo

echo "--- Kernel Command Line ---"
cat /proc/cmdline | grep -o 'pti=[^ ]*' || echo "pti parameter not set (auto)"
echo

echo "--- KPTI Config ---"
grep CONFIG_PAGE_TABLE_ISOLATION /boot/config-$(uname -r) 2>/dev/null || echo "Config not found"
echo

echo "--- CPU Flags (Intel) ---"
grep -m1 '^flags' /proc/cpuinfo | grep -oE '\b(rdcl_no|pku|pcid|invpcid)\b' | sort -u | tr '\n' ' '
echo
echo

echo "--- dmesg KPTI ---"
dmesg -T | grep -i "page tables isolation" | head -5
echo

echo "--- Performance Hints ---"
echo "Context switches/sec: $(grep ctxt /proc/stat | awk '{print $2}')"
echo "Processes: $(ps aux --no-headers | wc -l)"
```

#### Ansible-плейбук для аудита KPTI на парке серверов
```yaml
---
- name: Audit KPTI status across fleet
  hosts: all
  become: true
  gather_facts: true
  tasks:
    - name: Check meltdown mitigation status
      ansible.builtin.shell: cat /sys/devices/system/cpu/vulnerabilities/meltdown
      register: meltdown_status
      changed_when: false
      failed_when: false

    - name: Check kernel cmdline for pti
      ansible.builtin.shell: cat /proc/cmdline | grep -o 'pti=[^ ]*' || echo "auto"
      register: pti_cmdline
      changed_when: false

    - name: Check KPTI kernel config
      ansible.builtin.shell: grep CONFIG_PAGE_TABLE_ISOLATION /boot/config-$(uname -r) 2>/dev/null || echo "not found"
      register: kpti_config
      changed_when: false

    - name: Check CPU flags for hardware mitigation
      ansible.builtin.shell: grep -m1 '^flags' /proc/cpuinfo | grep -o '\brdcl_no\b' || echo "absent"
      register: cpu_rdcl_no
      changed_when: false

    - name: Output summary
      ansible.builtin.debug:
        msg:
          - "Host: {{ inventory_hostname }}"
          - "Meltdown status: {{ meltdown_status.stdout }}"
          - "Kernel pti param: {{ pti_cmdline.stdout }}"
          - "Kernel config: {{ kpti_config.stdout }}"
          - "CPU rdcl_no flag: {{ cpu_rdcl_no.stdout }}"
```

### 5. Особенности в контейнерах и виртуализации

#### Контейнеры (Docker, Podman, containerd)
- **KPTI работает на уровне хоста.** Контейнеры делят ядро с хостом, поэтому статус KPTI определяется настройками хостового ядра.
- Внутри контейнера проверка через `/sys/devices/system/cpu/vulnerabilities/meltdown` покажет статус **хоста**.
- Накладные расходы KPTI влияют на контейнеры так же, как и на нативные процессы.

```bash
# Проверка внутри контейнера (показывает статус хоста)
docker run --rm alpine cat /sys/devices/system/cpu/vulnerabilities/meltdown

# Для изоляции контейнеров от KPTI-накладных расходов — используйте --cpuset-cpus
# или запускайте критические по latency нагрузки на выделенных ядрах (cpu pinning)
docker run --cpuset-cpus="2,3" my-latency-sensitive-app
```

#### Виртуальные машины (KVM/QEMU, libvirt)
- **Гостевая ОС** имеет свой экземпляр KPTI (если её ядро его поддерживает).
- **Хост** имеет свой KPTI.
- Накладные расходы **суммируются** (двойное переключение таблиц страниц: guest user→guest kernel→host kernel).

```xml
<!-- libvirt: передача флагов CPU для включения PCID/INVPCID в гость -->
<cpu mode='host-passthrough' check='partial'>
  <feature policy='require' name='pcid'/>
  <feature policy='require' name='invpcid'/>
</cpu>

<!-- Для Intel: включение VMX (EPT/VPID) снижает накладные расходы вложенной виртуализации -->
<features>
  <kvm>
    <hidden state='on'/>
  </kvm>
</features>
```

**Рекомендации для виртуализации:**
1. Используйте `cpu mode='host-passthrough'` для передачи PCID/INVPCID в гость.
2. На хосте оставьте `pti=auto` (по умолчанию).
3. В гостевой ОС — тоже `pti=auto`.
4. Для критичных по производительности VM рассмотрите выделенные ядра (`cpuset` + `emulatorpin`).

### 6. Troubleshooting и известные проблемы

#### Проблема: Система не загружается после `pti=on`
**Причина:** Очень старые загрузчики (GRUB Legacy, старые версии systemd-boot) или несовместимые параметры ядра.
**Решение:**
1. Загрузитесь с Live USB.
2. Смонтируйте корневую ФС и `/boot`.
3. Отредактируйте `/etc/default/grub` (уберите `pti=on`).
4. `chroot` и `update-grub`.

#### Проблема: `Mitigation: PTI` на современном CPU (где должен быть `Not affected`)
**Причина:** Ядро не распознало аппаратную защиту или флаг `rdcl_no` не выставлен BIOS/микрокодом.
**Диагностика:**
```bash
# Проверка микрокода
dmesg | grep -i microcode
# Обновление микрокода (Debian/Ubuntu)
apt-get install intel-microcode && update-initramfs -u
# RHEL/Fedora
dnf install microcode_ctl && systemctl enable --now microcode
```
**Решение:** Обновить BIOS/UEFI и микрокод процессора. Если не помогло — `pti=off` в GRUB (на свой риск).

#### Проблема: Высокие накладные расходы на старых CPU без PCID
**Симптомы:** Высокое `%sys` в `top`, много `context switches`, деградация 20%+ на syscall-heavy нагрузках.
**Меры:**
1. `pti=off` в GRUB (если физическая безопасность хоста гарантирована).
2. Обновление железа (CPU с PCID: Intel Westmere 2010+, все современные AMD).
3. Тюнинг нагрузки: батчинг системных вызовов (io_uring, epoll), уменьшение частоты вызовов.

#### Проблема: KPTI ломает старые проприетарные модули ядра
**Причина:** Модули, напрямую обращающиеся к пользовательским адресам без макросов `access_ok()` / `get_user()`.
**Решение:** Обновить модуль или использовать `pti=off` (небезопасно).

### 7. Best Practices для DevOps/SRE/SysAdmin

1. **По умолчанию — `pti=auto`.** Доверяйте ядру выбор. Ядро отключит KPTI на неподверженных CPU (Intel с `rdcl_no`, AMD, ARM с аппаратной изоляцией).
2. **Принудительно включайте `pti=on` только если:**
   - Оборудование уязвимо И нет возможности обновить микрокод/BIOS.
   - Требуется максимальная защита KASLR (например, системы высокой секретности).
3. **Принудительно отключайте `pti=off` только если:**
   - CPU старый (нет PCID) И накладные расходы критичны И физический доступ изолирован.
   - Вы проводите бенчмарки и нужно измерить "чистую" производительность.
4. **Мониторьте** `/sys/devices/system/cpu/vulnerabilities/meltdown` в системах мониторинга (Prometheus node_exporter экспортирует это как `node_cpu_vulnerability_meltdown`).
5. **В CI/CD пайплайнах** добавляйте проверку статуса уязвимостей как quality gate для staging/prod сред.
6. **Документируйте** решение по KPTI в runbook'ах инцидент-респонса (секция "Hardware Vulnerabilities").

### 8. Связанные механизмы безопасности

| Механизм | Связь с KPTI |
| :--- | :--- |
| **KASLR** | KPTI скрывает маппинг ядра, усиливая рандомизацию |
| **Retpoline** | Защита от Spectre v2; работает независимо, но часто управляется вместе (`mitigations=`) |
| **SMEP/SMAP** | Аппаратные фичи, дополняющие KPTI (запрет выполнения/доступа user-space из kernel) |
| **KPTI + PCID** | Комбинация, снижающая накладные расходы до приемлемых |
| **LA57 (5-level paging)** | Расширяет адресное пространство; работает с KPTI без конфликтов |

## Дополнительная информация

### См. также
- [KASLR (Kernel Address Space Layout Randomization)](./KASLR.md)
- [Виртуальная и физическая память в Linux](../../Core/memory/virtual_vs_physical_memory.md)
- [Безопасность модулей ядра](./kernel_module_security.md) — подпись и контроль загрузки модулей
- [Харденинг ядра Linux](./Kernel/hardening.md)
- [Обзор механизмов безопасности Linux](../Linux_Security_Mechanisms_Overview.md)
- [CPU Diagnostics: уязвимости](../../Diagnostics/Hardware/cpu_info.md#проверка-уязвимостей-cpu)