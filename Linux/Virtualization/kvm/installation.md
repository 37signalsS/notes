# Установка и настройка KVM

В данном файле приведено пошаговое руководство по подготовке системы, установке программного стека KVM/QEMU, автоматизации развертывания, hardening'у хоста, настройке сети и последующей валидации. Архитектурный обзор и теоретические основы доступны в [KVM — Обзор и архитектура](./overview.md).

## Определения

Основные определения (KVM, QEMU, libvirt, virtio, sVirt) и описание архитектуры взаимодействия компонентов представлены в разделе **[KVM — Обзор и архитектура](./overview.md#определения)**.

## Базовые концепции

### Требования к системе и среде

Для полноценной работы гипервизора необходимо выполнение следующих условий:

| Параметр | Описание | Метод проверки |
| :--- | :--- | :--- |
| **Виртуализация CPU** | Поддержка инструкций VMX (Intel) или SVM (AMD). | `grep -Eoc '(vmx|svm)' /proc/cpuinfo` |
| **BIOS/UEFI** | Аппаратная виртуализация должна быть включена (Intel VT-d / AMD-V). | Утилита `virt-host-validate` |
| **IOMMU (VT-d/AMD-Vi)** | Требуется для прямого проброса PCI-устройств в ВМ. | `dmesg | grep -i iommu` |
| **UEFI Support** | Поддержка современной загрузки через GPT/Secure Boot. | Наличие пакета `ovmf` |
| **Группы прав** | Доступ пользователя к сокету управления libvirt. | Группы `libvirt` и `kvm` |

### Компоненты программного стека

Набор пакетов зависит от используемого дистрибутива, но функционально они идентичны.

#### Debian / Ubuntu (Apt)
- `qemu-system-x86`: Основной эмулятор и виртуализатор.
- `libvirt-daemon-system`: Демон `libvirtd` и системные конфиги.
- `libvirt-clients`: CLI-утилиты (`virsh`).
- `virtinst`: Утилита `virt-install`.
- `bridge-utils`: Устаревшие инструменты для L2 Bridge (заменяются `iproute2`).
- `ovmf`: UEFI прошивки для ВМ.
- `qemu-guest-agent`: Демон внутри гостевой ОС для интеграции с гипервизором.
- `libosinfo-bin`: База данных гостевых ОС для `virt-install` (автоматический подбор `--os-variant`).

#### RHEL / CentOS / Rocky / AlmaLinux (Dnf)
- `qemu-kvm`: Оптимизированный QEMU для KVM.
- `libvirt`: Весь стек управления libvirt.
- `virt-install`: Инструмент создания ВМ.
- `virt-viewer`: Легковесная консоль для подключения к ВМ.
- `edk2-ovmf`: UEFI прошивки для ВМ.

### Безопасность хоста и доступ к libvirt

Libvirt обеспечивает изоляцию процессов ВМ через sVirt и управление доступом через polkit.

**sVirt (Secure Virtualization):**
Автоматически применяет метки SELinux или AppArmor к процессам QEMU, предотвращая доступ одной ВМ к ресурсам другой. По умолчанию активно в RHEL/CentOS/Fedora и Ubuntu 20.04+.

**Управление доступом (polkit):**
Для неинтерактивного управления (например, через Ansible) можно настроить правила polkit, позволяющие пользователям группы `libvirt` управлять ВМ без `sudo`:

```bash
# /etc/polkit-1/rules.d/50-libvirt-admin.rules
polkit.addRule(function(action, subject) {
  if (action.id.startsWith("org.libvirt.unix.manage") &&
      subject.isInGroup("libvirt")) {
    return polkit.Result.YES;
  }
});
```

После изменения правил polkit перезапустите службу:
```bash
sudo systemctl restart polkit
```

**Удаленный доступ к libvirt:**
- **SSH-туннель (рекомендуется):** `qemu+ssh://host/system` — шифрование через SSH, без открытия дополнительных портов.
- **TLS:** Порт 16509/TCP. Требует настройки сертификатов CA в `/etc/pki/` и включения `listen_tls` в `/etc/libvirt/libvirtd.conf`.
- **TCP (не рекомендуется):** Порт 16508/TCP без шифрования. Допустимо только в доверенных изолированных сегментах.

### Файрвол и сетевые порты

Libvirt использует следующие порты, которые должны быть разрешены на хосте:

| Порт | Протокол | Назначение |
| :--- | :--- | :--- |
| **16509** | TCP | Удаленное управление libvirt через TLS. |
| **5900–5910** | TCP | VNC-консоли ВМ (по одной на каждую запущенную ВМ). |
| **6080** | TCP | noVNC (веб-консоль, если настроено). |
| **22** | TCP | SSH для туннелирования миграции и управления. |

#### Firewalld (RHEL / Rocky / AlmaLinux / Fedora)
```bash
# Статическая зона для хостов виртуализации
sudo firewall-cmd --permanent --zone=libvirt --add-service=ssh
sudo firewall-cmd --permanent --zone=libvirt --add-port=16509/tcp
sudo firewall-cmd --permanent --zone=libvirt --add-port=5900-5910/tcp
sudo firewall-cmd --permanent --zone=libvirt --add-port=6080/tcp

# Назначение интерфейса моста vmbr0 в зону libvirt
sudo firewall-cmd --permanent --zone=libvirt --add-interface=vmbr0
sudo firewall-cmd --reload
```

#### UFW (Ubuntu / Debian)
```bash
sudo ufw allow ssh
sudo ufw allow 16509/tcp
sudo ufw allow 5900:5910/tcp
sudo ufw allow 6080/tcp
sudo ufw reload
```

#### nftables (универсально)
```bash
sudo nft add rule inet filter input tcp dport { ssh, 16509, 5900-5910, 6080 } accept
```

### Параметры ядра хоста для виртуализации

Гостевые нагрузки накладывают специфические требования на планировщик ядра хоста (L0).

**Рекомендуемые параметры GRUB для production-хостов:**
- **`intel_pstate=disable`** + **`acpi-cpufreq`:** На системах Intel позволяет полный контроль над частотой CPU через `cpufreq`. Полезно для фиксированной производительности, но снижает энергоэффективность.
- **`nohz_full=<cores>`:** Отключает периодические tick на указанных ядрах для снижения джиттера.
- **`isolcpus=<cores>`:** Исключает ядра из планировщика CFS для ручного управления (через `cset` или `taskset`).
- **`rcu_nocbs=<cores>`:** Перенос обработки RCU callbacks на отдельные ядра, снижая прерывания на ядрах, выделенных под ВМ.
- **`transparent_hugepage=never`:** Отключает THP для баз данных и latency-sensitive workloads.

Пример строки в `/etc/default/grub` (Ubuntu/Debian):
```text
GRUB_CMDLINE_LINUX_DEFAULT="quiet splash intel_pstate=disable nohz_full=2-11 isolcpus=2-11 rcu_nocbs=2-11 transparent_hugepage=never"
```

После изменения обновите конфигурацию GRUB и перезагрузитесь.

## Практические сценарии

### Сценарий 1: Проверка аппаратной готовности

Этот этап выполняется ДО установки пакетов для выявления потенциальных проблем.

**1. Проверка флагов процессора:**
```bash
grep -Eoc '(vmx|svm)' /proc/cpuinfo
# → результат > 0 означает наличие аппаратной поддержки.
```

**2. Глубокая валидация (рекомендуется):**
После установки пакета `libvirt-clients` используйте наиболее полную утилиту:
```bash
virt-host-validate qemu
# → Ожидается "PASS" для большинства критических проверок.
# → "WARN" по IOMMU допустим, если вы не планируете проброс PCI-устройств.
```

**3. Активация IOMMU (для Passthrough):**
Если планируется проброс видеокарт или сетевых адаптеров, добавьте параметры в `/etc/default/grub`:
- **Intel:** `intel_iommu=on iommu=pt`
- **AMD:** `amd_iommu=on iommu=pt`

Обновите конфигурацию и перезагрузитесь:
- Ubuntu: `sudo update-grub`
- RHEL: `sudo grub2-mkconfig -o /boot/grub2/grub.cfg`

### Сценарий 2: Установка стека виртуализации

#### Вариант А: Debian / Ubuntu 24.04+
```bash
sudo apt update
sudo apt install -y qemu-system-x86 libvirt-daemon-system libvirt-clients virtinst ovmf virt-manager qemu-guest-agent libosinfo-bin
```

#### Вариант Б: RHEL 9 / AlmaLinux / Rocky
```bash
# Установка группы пакетов для виртуализации
sudo dnf groupinstall -y "Virtualization Host"
sudo dnf install -y virt-install virt-viewer
```

### Сценарий 3: Постустановочная настройка

**1. Активация служб:**
```bash
sudo systemctl enable --now libvirtd
# Проверка сокета
virsh uri # → Ожидается: qemu:///system
```

**2. Настройка прав доступа:**
Чтобы управлять ВМ без `sudo`, добавьте пользователя в соответствующие группы:
```bash
sudo usermod -aG libvirt $USER
sudo usermod -aG kvm $USER
# → Необходимо перевойти в сессию (logout/login).
```

**3. Проверка хранилища (Storage Pool):**
По умолчанию libvirt использует `/var/lib/libvirt/images`. Убедитесь, что пул активен:
```bash
virsh pool-list --all
# Если default пул не активен:
virsh pool-start default
virsh pool-autostart default
```

### Сценарий 4: Идемпотентный скрипт установки (DevOps/SRE)

Скрипт для автоматизированных систем (Ansible, SaltStack, Puppet). Гарантирует идемпотентность — повторный запуск не ломает систему.

```bash
#!/bin/bash
# kvm-bootstrap.sh — идемпотентная установка KVM
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Запустите от root или через sudo."
  exit 1
fi

if command -v apt-get >/dev/null 2>&1; then
  apt-get update
  apt-get install -y qemu-system-x86 libvirt-daemon-system libvirt-clients virtinst ovmf qemu-guest-agent
elif command -v dnf >/dev/null 2>&1; then
  dnf groupinstall -y "Virtualization Host"
  dnf install -y virt-install virt-viewer
else
  echo "Неподдерживаемый дистрибутив."
  exit 1
fi

# Активация служб (идемпотентно)
systemctl enable --now libvirtd

# Группы (идемпотентно)
usermod -aG libvirt "$SUDO_USER" || true
usermod -aG kvm "$SUDO_USER" || true

# Пул по умолчанию
virsh pool-list --all | grep -q default || {
  virsh pool-define-as default dir - - - - "/var/lib/libvirt/images"
  virsh pool-build default
  virsh pool-start default
  virsh pool-autostart default
}

echo "KVM готов. Перевойдите пользователя $SUDO_USER."
```

### Сценарий 5: Настройка сетевого моста (L2 Bridge)

Для предоставления ВМ доступа в физическую сеть хоста.

#### Способ 1: NetworkManager (nmcli) — универсальный для RHEL и современных Ubuntu
```bash
# Создание интерфейса моста
nmcli con add type bridge ifname br0 con-name br0
# Привязка физического интерфейса (напр. eth0) к мосту
nmcli con add type bridge-slave ifname eth0 con-name br0-slave master br0
# Поднятие моста
nmcli con up br0
```

#### Способ 2: Netplan (Ubuntu)
Пример `/etc/netplan/01-netcfg.yaml`:
```yaml
network:
  version: 2
  ethernets:
    enp3s0:
      dhcp4: no
  bridges:
    br0:
      interfaces: [enp3s0]
      dhcp4: yes
      parameters:
        stp: false
```
Примените изменения: `sudo netplan apply`.

### Сценарий 6: Настройка файрвола для libvirt

Настройка firewall для разрешения управления libvirt и консольного доступа.

#### Firewalld (RHEL / Rocky / AlmaLinux / Fedora)
```bash
# Статическая зона для хостов виртуализации
sudo firewall-cmd --permanent --zone=libvirt --add-service=ssh
sudo firewall-cmd --permanent --zone=libvirt --add-port=16509/tcp
sudo firewall-cmd --permanent --zone=libvirt --add-port=5900-5910/tcp
sudo firewall-cmd --permanent --zone=libvirt --add-port=6080/tcp
sudo firewall-cmd --permanent --zone=libvirt --add-interface=br0
sudo firewall-cmd --reload
```

#### UFW (Ubuntu / Debian)
```bash
sudo ufw allow ssh
sudo ufw allow 16509/tcp
sudo ufw allow 5900:5910/tcp
sudo ufw allow 6080/tcp
sudo ufw reload
```

### Сценарий 7: Тонкая настройка параметров ядра хоста

Для production-хостов с высокой нагрузкой на виртуализацию.

```bash
# Пример параметров GRUB для хоста с 16 ядрами (изоляция ядер 2–15)
GRUB_CMDLINE_LINUX_DEFAULT="quiet splash intel_pstate=disable nohz_full=2-15 isolcpus=2-15 rcu_nocbs=2-15 transparent_hugepage=never"
```

Применение:
- Ubuntu/Debian: `sudo update-grub`
- RHEL/Rocky: `sudo grub2-mkconfig -o /boot/grub2/grub.cfg`

Проверка загруженных параметров:
```bash
cat /proc/cmdline
# → Ожидается наличие добавленных параметров.
```

### Сценарий 8: Вложенная виртуализация (Nested Virtualization)

Позволяет запускать гипервизор (KVM) внутри виртуальной машины.

Подробные инструкции по активации на хосте (L0) и настройке ВМ (L1) вынесены в специализированный SSoT-файл:
**[Вложенная виртуализация: Практические сценарии](../nested_virtualization/practical_scenarios.md)**.

Краткая проверка статуса:
```bash
# Для Intel
cat /sys/module/kvm_intel/parameters/nested
# → Y или 1 означает "включено"

# Для AMD
cat /sys/module/kvm_amd/parameters/nested
# → 1 означает "включено"
```

### Сценарий 9: Валидация установки (Checklist)

Комплексная проверка корректности развертывания.

```bash
# 1. Модуль KVM загружен
lsmod | grep -E 'kvm_(intel|amd)'
# → kvm_intel  или kvm_amd

# 2. Доступ к /dev/kvm
ls -la /dev/kvm
# → crw-rw---- 1 root kvm ...

# 3. Демон libvirtd активен
systemctl is-active libvirtd
# → active

# 4. URI системного демона
virsh uri
# → qemu:///system

# 5. Пул по умолчанию активен и автозапускается
virsh pool-list --all
# → default   active   yes

# 6. Сетевая виртуальная сеть active
virsh net-list --all
# → default   active   yes

# 7. Группы пользователя
groups $USER | grep -qE 'kvm|libvirt'
# → true

# 8. Виртуализация доступна процессору
egrep -c '(vmx|svm)' /proc/cpuinfo
# → число > 0

# 9. IOMMU активен (если требуется passthrough)
dmesg | grep -iE 'intel.*iommu|amd.*iommu'
# → DMAR: IOMMU enabled
```

### Сценарий 10: Удаление и очистка (Uninstall)

Безопасное удаление стека виртуализации и связанных ресурсов.

```bash
# 1. Остановка и undefine всех ВМ
for vm in $(virsh list --name --all); do
  virsh destroy "$vm" 2>/dev/null || true
  virsh undefine "$vm" --remove-all-storage --snapshots-metadata
done

# 2. Удаление сетей libvirt
virsh net-list --all --name | xargs -I{} virsh net-destroy {} 2>/dev/null || true
virsh net-list --all --name | xargs -I{} virsh net-undefine {} 2>/dev/null || true

# 3. Удаление пулов (опционально)
virsh pool-list --all --name | xargs -I{} virsh pool-destroy {} 2>/dev/null || true
virsh pool-list --all --name | xargs -I{} virsh pool-undefine {} 2>/dev/null || true

# 4. Удаление пакетов (Debian/Ubuntu)
apt-get purge -y qemu-system-x86 libvirt-daemon-system libvirt-clients virtinst ovmf qemu-guest-agent

# 5. Удаление пакетов (RHEL/Rocky)
dnf remove -y @virtualization qemu-kvm libvirt virt-install

# 6. Очистка конфигов и данных
rm -rf /var/lib/libvirt /etc/libvirt /var/log/libvirt

# 7. Выгрузка модулей ядра
modprobe -r kvm_intel 2>/dev/null || true
modprobe -r kvm_amd 2>/dev/null || true
```

### Сценарий 11: Live patching ядра KVM-хоста

Обновление ядра KVM-хоста без перезагрузки и простоя виртуальных машин.

**Canonical Livepatch (Ubuntu):**
```bash
# Установка
sudo snap install canonical-livepatch
sudo canonical-livepatch enable <your-token>

# Проверка
sudo canonical-livepatch status --verbose
# → kernel: 6.5.0-44-generic
#   CVEs: 5 applied, 0 pending
#   Status: Up to date

# Откат патча (если проблемы)
sudo canonical-livepatch disable
sudo snap remove canonical-livepatch
```

**kpatch (RHEL/Rocky/Fedora):**
```bash
# Установка
sudo dnf install kpatch kpatch-dnf

# Просмотр доступных патчей
sudo kpatch list
# → Installed patch modules:
#   /var/lib/kpatch/4.18.0-305.el8.x86_64/

# Установка security patch
sudo dnf install kpatch-patch-<version>

# Проверка
sudo kpatch list
# → 1 kpatch module(s) loaded.
```

**Проверка целостности:**
```bash
# Проверка текущего ядра
uname -r
# → 6.5.0-44-generic (с live patch)

# Проверка applied patches
sudo kpatch list  # RHEL
sudo canonical-livepatch status  # Ubuntu
```

**Ограничения:** Live patching обновляет только security patches в ядре. Не обновляет модули ядра, не заменяет major kernel version. Для полного обновления требуется перезагрузка.

## Дополнительная информация

- [KVM — Обзор и архитектура](./overview.md) — SSoT по теории и механизмам.
- [Управление виртуальными машинами](./management.md) — создание ВМ и работа с `virsh`.
- [Диагностика и решение проблем](./troubleshooting.md) — логи и типичные ошибки.
- [Оптимизация KVM (2025–2026)](./performance_tuning_2026.md) — современные методы ускорения.
- [Автоматизация KVM](./kvm_automation.md) — Ansible, Terraform, Packer.
- [Мониторинг KVM](./kvm_monitoring.md) — Prometheus, libvirt_exporter, Grafana.
- [Вложенная виртуализация (Nested)](../nested_virtualization/practical_scenarios.md) — расширенная настройка.
- [Linux Bridge: Концепции](../../Networking/Concepts/linux_bridge.md) — архитектура L2-сетей.
- [Настройка GRUB](../../SystemAdministration/grub.md) — управление параметрами ядра.
- [Безопасность: AppArmor](../../Security/Mechanisms/AppArmor.md) — MAC-механизм для изоляции QEMU.
- [Безопасность: SELinux](../../Security/Mechanisms/SELinux.md) — метки и sVirt.
- [Настройка файрволов](../../Networking/Settings/tools/firewall_common.md) — firewalld, UFW, nftables.
- [Live patching ядра](../../Linux/Core/kernel/live_patching.md) — kpatch, canonical-livepatch.
- [Сетевые основы KVM](./kvm_networking_fundamentals.md) — dnsmasq, nwfilter, port forwarding.
- [Безопасность KVM](./kvm_security_hardening.md) — sVirt, polkit, LUKS, CIS Benchmark.
- [UEFI, Secure Boot и vTPM](./kvm_uefi_secure_boot.md) — настройка UEFI, Secure Boot, vTPM.
