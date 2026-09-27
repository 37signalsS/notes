# Безопасность KVM-хостов: Hardening, sVirt, polkit, LUKS

В данном файле описывается комплексный подход к защите KVM-хостов и виртуальных машин: изоляция через sVirt (SELinux/AppArmor), управление доступом через polkit и libvirt ACL, шифрование дисков ВМ через LUKS, сетевая изоляция через nwfilter и CIS Benchmark. Общие принципы MAC-механизмов описаны в [SELinux](../../Linux/Security/Mechanisms/SELinux.md) и [AppArmor](../../Linux/Security/Mechanisms/AppArmor.md), а сетевая фильтрация — в [Сетевые основы KVM](./kvm_networking_fundamentals.md).

## Определения

**sVirt (Secure Virtualization)** — технология интеграции libvirt с системами мандатного управления доступом (SELinux, AppArmor) для автоматической изоляции процессов QEMU друг от друга и от хоста. Каждый процесс ВМ получает уникальную метку, ограничивающую доступ к ресурсам.

**MCS (Multi-Category Security)** — расширение SELinux, используемое sVirt для назначения уникальных категорий (например, `s0:c123,c456`) каждой ВМ, обеспечивая горизонтальную изоляцию.

**polkit (PolicyKit)** — фреймворк для управления авторизацией в Linux-системах. В контексте libvirt позволяет настраивать精细化ный доступ к управлению ВМ без root-привилегий.

**libvirt ACL** — система контроля доступа, встроенная в libvirt, определяющая, какие операции (start, stop, migrate) доступны конкретному пользователю для конкретных ресурсов (домены, сети, хранилища).

**LUKS (Linux Unified Key Setup)** — стандарт шифрования блочных устройств в Linux. В контексте KVM позволяет шифровать образы дисков ВМ на уровне хоста, обеспечивая конфиденциальность данных при краже хранилища.

**NWFilter (Network Filter)** — механизм libvirt для фильтрации сетевого трафика ВМ на уровне vNIC. Предотвращает MAC/IP spoofing, ARP attacks и несанкционированный доступ к сетевым ресурсам.

**CIS Benchmark** — набор рекомендаций по настройке безопасности для различных платформ. Для KVM включает проверки прав доступа, сетевые порты, логирование и изоляцию.

**QEMU Process Isolation** — изоляция каждого процесса QEMU через сопоставление MAC/DAC, ограничение системных вызовов (seccomp) и изоляцию namespaces.

## Базовые концепции

### Архитектура безопасности KVM

Безопасность KVM строится на нескольких уровнях:

```
┌─────────────────────────────────────────────┐
│            Уровень 3: Сеть                  │
│  nwfilter (MAC/IP filtering)                │
│  iptables/nftables (host firewall)          │
├─────────────────────────────────────────────┤
│            Уровень 2: Процесс               │
│  sVirt (SELinux/AppArmor)                   │
│  seccomp (syscall filtering)                │
│  namespaces (PID, NET, MNT)                 │
├─────────────────────────────────────────────┤
│            Уровень 1: Данные                │
│  LUKS (диски ВМ)                            │
│  qcow2 encryption                           │
├─────────────────────────────────────────────┤
│            Уровень 0: Хост                  │
│  CIS Benchmark                              │
│  polkit/libvirt ACL (RBAC)                  │
│  Audit logging (auditd)                     │
└─────────────────────────────────────────────┘
```

### sVirt: изоляция через SELinux

sVirt автоматически назначает уникальные SELinux-метки каждому процессу QEMU и связанным файлам. Это предотвращает кросс-VM атаки.

**Типы контекстов:**

| Контекст | Описание |
| :--- | :--- |
| `svirt_t` | Тип процесса QEMU/KVM. Определяет, что процесс может выполнять. |
| `svirt_image_t` | Тип файлов образов дисков ВМ. Определяет, какие файлы может открывать QEMU. |
| `svirt_content_t` | Тип файлов данных ВМ (не образов). Для файлов, создаваемых внутри гостя. |
| `virt_image_t` | Синоним `svirt_image_t` для RHEL 8+. |

**MCS-метки:**
```bash
# Просмотр контекста процесса QEMU
ps -eZ | grep qemu-kvm
# → system_u:system_r:svirt_t:s0:c123,c456  12345 ?  00:00:01 qemu-kvm

# Просмотр контекста образа диска
ls -Z /var/lib/libvirt/images/web-server-01.qcow2
# → system_u:object_r:virt_image_t:s0  /var/lib/libvirt/images/web-server-01.qcow2

# MCS-коды (c123,c456) уникальны для каждой ВМ
# Другая ВМ получит: svirt_t:s0:c789,c012
```

**Проверка SELinux для KVM:**
```bash
# Статус SELinux
getenforce
# → Enforcing

# Просмотр AVC-событий (блокировки)
ausearch -m avc --start today | grep qemu
# → type=AVC msg=audit(1234567890.123:456): avc: denied { read } for pid=12345 comm="qemu-kvm" name="data.img" scontext=system_u:system_r:svirt_t:s0:c123,c456 tcontext=system_u:object_r:virt_image_t:s0 tclass=file

# Разрешение блокировки (если обоснованно)
ausearch -m avc --start today | grep qemu | audit2allow -M my_qemu_fix
sudo semodule -i my_qemu_fix.pp
```

**Настройка нестандартных путей к образам:**
```bash
# Если образы хранятся вне /var/lib/libvirt/images
sudo semanage fcontext -a -t virt_image_t "/mnt/storage/vms(/.*)?"
sudo restorecon -Rv /mnt/storage/vms

# Проверка
ls -Z /mnt/storage/vms/
# → system_u:object_r:virt_image_t:s0  web-server-01.qcow2
```

### sVirt: изоляция через AppArmor

AppArmor использует профили для ограничения доступа процессов QEMU к файлам и ресурсам.

**Просмотр активного профиля:**
```bash
# Проверка AppArmor
aa-status | grep qemu
# → /usr/sbin/libvirtd (12345) profile
# → /usr/lib/libvirt/qemu/qemu-system-x86_64 (12346) profile

# Профиль QEMU
cat /etc/apparmor.d/usr.lib.libvirt.qemu.qemu-system-x86_64
```

**Добавление нестандартного пути:**
```bash
# Создание пользовательского конфига
echo '/mnt/storage/vms/** rwk,' | \
  sudo tee /etc/apparmor.d/abstractions/libvirt-qemu.d/custom-paths

# Перезагрузка AppArmor
sudo systemctl restart apparmor

# Проверка
sudo aa-status | grep qemu
```

**Переключение в режим complain (для отладки):**
```bash
# Временное отключение блокировок
sudo aa-complain /usr/lib/libvirt/qemu/*

# Возврат в enforce
sudo aa-enforce /usr/lib/libvirt/qemu/*
```

### polkit: управление доступом к libvirt

polkit позволяет настраивать精细化ный доступ к управлению ВМ без передачи root-привилегий.

**Правила polkit для libvirt:**
```javascript
// /etc/polkit-1/rules.d/50-libvirt-admin.rules
// Разрешение пользователям группы libvirt управлять ВМ
polkit.addRule(function(action, subject) {
  if (action.id.startsWith("org.libvirt.unix.manage") &&
      subject.isInGroup("libvirt")) {
    return polkit.Result.YES;
  }
});
```

**Ограничение только конкретными операциями:**
```javascript
// /etc/polkit-1/rules.d/60-libvirt-read-only.rules
// Разрешение только чтения для группы libvirt-users
polkit.addRule(function(action, subject) {
  if (action.id == "org.libvirt.unix.manage" &&
      subject.isInGroup("libvirt-users")) {
    // Разрешить только list, info, dumpxml
    if (action.lookup("domain") != undefined) {
      var verb = action.lookup("verb");
      if (verb == "start" || verb == "stop" || verb == "destroy") {
        return polkit.Result.NO;
      }
    }
    return polkit.Result.YES;
  }
});
```

**Проверка полномочий:**
```bash
# Просмотр доступных polkit-действий для libvirt
pkaction --action-id org.libvirt.unix.manage --verbose

# Тестирование от имени пользователя
sudo -u libvirt-user polkitctl action org.libvirt.unix.manage \
  --process $$ --enable-internal-agent
```

### libvirt ACL: управление доступом к ресурсам

libvirt ACL позволяет привязывать права доступа к конкретным пользователям и ресурсам.

**Включение ACL:**
```bash
# /etc/libvirt/libvirtd.conf
# Включение polkit для неинтерактивных соединений
unix_sock_group = "libvirt"
unix_sock_ro_perms = "0777"
unix_sock_rw_perms = "0770"

# Включение ACL
access_drivers = [ "polkit" ]
```

**Настройка ACL через virsh:**
```bash
# Просмотр текущих ACL
virsh nwfilter-binding-list

# Установка ACL для пользователя
virsh -c qemu:///system nwfilter-binding-list \
  --user admin --group libvirt
```

### Шифрование дисков ВМ через LUKS

LUKS позволяет шифровать образы дисков ВМ, обеспечивая конфиденциальность при физическом доступе к хранилищу.

**Создание зашифрованного образа:**
```bash
# 1. Создание обычного образа
qemu-img create -f qcow2 /var/lib/libvirt/images/encrypted-vm.qcow2 50G

# 2. Шифрование через LUKS (на уровне блочного устройства)
# Для этого нужен loopback device или LVM LV
LOOP=$(sudo losetup -f --show /var/lib/libvirt/images/encrypted-vm.qcow2)
sudo cryptsetup luksFormat --type luks2 $LOOP
sudo cryptsetup luksOpen $LOOP encrypted-vm
sudo mkfs.ext4 /dev/mapper/encrypted-vm
sudo mount /dev/mapper/encrypted-vm /mnt/encrypted-vm

# 3. Использование LVM поверх LUKS
sudo pvcreate /dev/mapper/encrypted-vm
sudo vgcreate vg_encrypted /dev/mapper/encrypted-vm
sudo lvcreate -L 50G -n vm_disk vg_encrypted
```

**Автоматическое расшифрование при старте:**
```bash
# Создание keyfile
sudo dd if=/dev/urandom of=/etc/luks-key-vm bs=1 count=256
sudo chmod 400 /etc/luks-key-vm

# Добавление keyfile в LUKS
sudo cryptsetup luksAddKey /dev/loop0 /etc/luks-key-vm

# Расшифрование через keyfile
sudo cryptsetup luksOpen /dev/loop0 encrypted-vm \
  --key-file /etc/luks-key-vm
```

**Настройка systemd для автоматического расшифрования:**
```ini
# /etc/systemd/system/cryptsetup-vm.service
[Unit]
Description=Decrypt VM disk
After=local-fs.target
Before=libvirtd.service

[Service]
Type=oneshot
ExecStart=/sbin/cryptsetup luksOpen /dev/loop0 encrypted-vm --key-file /etc/luks-key-vm
ExecStop=/sbin/cryptsetup luksClose encrypted-vm
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

**Включение LUKS в XML ВМ:**
```xml
<domain type='kvm'>
  <devices>
    <disk type='block' device='disk'>
      <driver name='qemu' type='raw' cache='none' io='native'/>
      <source dev='/dev/mapper/encrypted-vm'/>
      <target dev='vda' bus='virtio'/>
    </disk>
  </devices>
</domain>
```

### CIS Benchmark для KVM-хостов

Ключевые проверки безопасности по CIS Benchmark Linux, адаптированные для KVM.

**Проверка прав на /dev/kvm:**
```bash
ls -la /dev/kvm
# → crw-rw---- 1 root kvm 10, 232 ... /dev/kvm
# Ожидается: root:kvm, 660

# Исправление (если неправильные права)
sudo chown root:kvm /dev/kvm
sudo chmod 660 /dev/kvm
```

**Проверка SELinux/AppArmor:**
```bash
# SELinux
getenforce
# → Enforcing (ожидается)

# AppArmor
aa-status
# →  profiles are in enforce mode (ожидается)
```

**Проверка сетевых портов:**
```bash
# Только разрешённые порты
ss -tlnp | grep -E '16509|5900|5901|22'
# → 16509 (libvirt TLS)
# → 5900-5910 (VNC)
# → 22 (SSH)

# Порты, которые НЕ должны быть открыты
ss -tlnp | grep -E '23|80|443|3389'
# → (пусто)
```

**Проверка SSH:**
```bash
# Root login должен быть отключен
grep PermitRootLogin /etc/ssh/sshd_config
# → PermitRootLogin no

# Password authentication отключена
grep PasswordAuthentication /etc/ssh/sshd_config
# → PasswordAuthentication no
```

**Проверка аудита:**
```bash
# auditd должен быть активен
systemctl is-active auditd
# → active

# Правила аудита для libvirt
auditctl -l | grep libvirt
# → -w /usr/sbin/libvirtd -p wa -k libvirt
# → -w /etc/libvirt/ -p wa -k libvirt-config
# → -w /var/lib/libvirt/ -p wa -k libvirt-storage
```

**Автоматизация через Ansible:**
```yaml
---
- name: Harden KVM hosts
  hosts: kvm_hosts
  become: yes
  roles:
    - dev-sec.os-hardening
    - dev-sec.ssh-hardening
    - dev-sec.kernel-hardening
  vars:
    sysctl_conf:
      - name: net.ipv4.ip_forward
        value: "1"  # Требуется для NAT ВМ
      - name: net.bridge.bridge-nf-call-iptables
        value: "1"
      - name: vm.max_map_count
        value: "262144"
```

### Аудит действий с libvirt через auditd

Настройка детального аудита всех действий с виртуальными машинами.

```bash
# Добавление правил аудита
sudo auditctl -w /usr/sbin/libvirtd -p wa -k libvirt
sudo auditctl -w /etc/libvirt/ -p wa -k libvirt-config
sudo auditctl -w /var/lib/libvirt/ -p wa -k libvirt-storage
sudo auditctl -w /var/run/libvirt/ -p wa -k libvirt-runtime

# Просмотр аудит-логов
sudo ausearch -k libvirt --start today
sudo aureport --summary

# Аудит конкретного действия
sudo ausearch -k libvirt -i | grep "start\|stop\|migrate"
```

## Практические сценарии

### Сценарий 1: Полный аудит безопасности KVM-хоста

```bash
#!/bin/bash
# kvm-security-audit.sh — комплексная проверка безопасности KVM

ERRORS=0
WARNINGS=0

echo "=== KVM Security Audit ==="

# 1. SELinux/AppArmor
echo -e "\n--- MAC Security ---"
if command -v getenforce &>/dev/null; then
  STATUS=$(getenforce)
  if [ "$STATUS" != "Enforcing" ]; then
    echo "[FAIL] SELinux not in Enforcing mode: $STATUS"
    ERRORS=$((ERRORS + 1))
  else
    echo "[OK] SELinux: Enforcing"
  fi
fi

if command -v aa-status &>/dev/null; then
  ENFORCE=$(aa-status | grep "profiles are in enforce" | wc -l)
  if [ "$ENFORCE" -eq 0 ]; then
    echo "[WARN] AppArmor not in enforce mode"
    WARNINGS=$((WARNINGS + 1))
  else
    echo "[OK] AppArmor: enforce mode"
  fi
fi

# 2. Права на /dev/kvm
echo -e "\n--- Device Permissions ---"
KVM_PERMS=$(ls -la /dev/kvm | awk '{print $1, $3, $4}')
if echo "$KVM_PERMS" | grep -q "root:kvm"; then
  echo "[OK] /dev/kvm: root:kvm"
else
  echo "[FAIL] /dev/kvm permissions: $KVM_PERMS"
  ERRORS=$((ERRORS + 1))
fi

# 3. SSH
echo -e "\n--- SSH Security ---"
if grep -q "PermitRootLogin no" /etc/ssh/sshd_config; then
  echo "[OK] SSH: root login disabled"
else
  echo "[FAIL] SSH: root login enabled"
  ERRORS=$((ERRORS + 1))
fi

# 4. Сетевые порты
echo -e "\n--- Network Ports ---"
OPEN_PORTS=$(ss -tlnp | grep -c -E '16509|5900|5901|22')
UNEXPECTED=$(ss -tlnp | grep -c -E '23|80|443|3389|8080')
if [ "$UNEXPECTED" -gt 0 ]; then
  echo "[WARN] Unexpected open ports detected"
  WARNINGS=$((WARNINGS + 1))
else
  echo "[OK] Only expected ports open"
fi

# 5. auditd
echo -e "\n--- Audit ---"
if systemctl is-active auditd &>/dev/null; then
  echo "[OK] auditd: active"
else
  echo "[FAIL] auditd: not active"
  ERRORS=$((ERRORS + 1))
fi

# 6. Polkit
echo -e "\n--- Polkit ---"
if [ -f /etc/polkit-1/rules.d/50-libvirt-admin.rules ]; then
  echo "[OK] Polkit rules for libvirt exist"
else
  echo "[WARN] No custom polkit rules for libvirt"
  WARNINGS=$((WARNINGS + 1))
fi

# Итог
echo -e "\n=== Audit Complete ==="
echo "Errors: $ERRORS, Warnings: $WARNINGS"
exit $ERRORS
```

### Сценарий 2: Настройка полного стека безопасности

```bash
# 1. SELinux enforcing
sudo setenforce 1
sudo sed -i 's/SELINUX=permissive/SELINUX=enforcing/' /etc/selinux/config

# 2. polkit rules
sudo mkdir -p /etc/polkit-1/rules.d
cat > /tmp/libvirt-polkit.rules << 'RULES'
polkit.addRule(function(action, subject) {
  if (action.id.startsWith("org.libvirt.unix.manage") &&
      subject.isInGroup("libvirt")) {
    return polkit.Result.YES;
  }
});
RULES
sudo cp /tmp/libvirt-polkit.rules /etc/polkit-1/rules.d/50-libvirt-admin.rules

# 3. Права на /dev/kvm
sudo chown root:kvm /dev/kvm
sudo chmod 660 /dev/kvm

# 4. SSH hardening
sudo sed -i 's/PermitRootLogin yes/PermitRootLogin no/' /etc/ssh/sshd_config
sudo sed -i 's/PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo systemctl restart sshd

# 5. Аудит
sudo auditctl -w /usr/sbin/libvirtd -p wa -k libvirt
sudo auditctl -w /etc/libvirt/ -p wa -k libvirt-config
sudo auditctl -w /var/lib/libvirt/ -p wa -k libvirt-storage

# 6. Перезапуск сервисов
sudo systemctl restart polkit
sudo systemctl restart auditd
```

### Сценарий 3: Диагностика блокировок sVirt

```bash
# Если ВМ не стартует с ошибкой "Permission denied"

# 1. Проверка SELinux
ausearch -m avc --start today | grep qemu
# → avc: denied { read } for ... scontext=svirt_t ... tcontext=virt_image_t

# 2. Генерация исправляющего модуля
ausearch -m avc --start today | grep qemu | audit2allow -M kvm_fix
sudo semodule -i kvm_fix.pp

# 3. Проверка контекстов
ls -Z /var/lib/libvirt/images/
# → ВСЕ файлы должны иметь virt_image_t

# 4. Если файлы с неправильным контекстом
sudo restorecon -Rv /var/lib/libvirt/images/

# 5. Или chcon (временно)
sudo chcon -t virt_image_t /var/lib/libvirt/images/*.qcow2
```

## Дополнительная информация

- [KVM — Обзор и архитектура](./overview.md) — sVirt, изоляция,安全 определения.
- [Установка и настройка KVM](./installation.md) — безопасность хоста, polkit, sVirt.
- [Сетевые основы KVM](./kvm_networking_fundamentals.md) — nwfilter, port forwarding.
- [Решение проблем (Troubleshooting)](./troubleshooting.md) — AppArmor/SELinux блокировки.
- [SELinux](../../Linux/Security/Mechanisms/SELinux.md) — sVirt, MCS,诊断 commands.
- [AppArmor](../../Linux/Security/Mechanisms/AppArmor.md) — profiles, QEMU isolation.
- [LUKS: Шифрование](../../Linux/FileSystems/LVM/advanced_topics/lvm_security_hardening.md) — полное руководство по LUKS2.
- [CIS Benchmark](../../Ansible/ansible-os-hardening.md) — автоматизация через Ansible.
- [auditd](../../Linux/SystemAdministration/Logging/auditd.md) — аудит событий ядра.
- [Lynis](../../Security/Tools/lynis.md) — аудит безопасности системы.
