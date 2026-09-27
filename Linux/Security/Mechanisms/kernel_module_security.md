# Безопасность модулей ядра Linux

## Определения и терминология

**Модуль ядра (kernel module)** — динамически загружаемый объектный код, расширяющий функциональность ядра без его пересборки. Модули используются для драйверов устройств, файловых систем, сетевых протоколов и механизмов безопасности.

**Подпись модулей (module signing)** — механизм аутентичности модулей ядра, использующий цифровые подписи для предотвращения загрузки несанкционированного или повреждённого кода.

### Ключевые термины

| Термин | Описание |
| :--- | :--- |
| **insmod** | Утилита для загрузки модуля ядра (минимальная проверка зависимостей) |
| **modprobe** | Утилита для загрузки модуля с автоматическим разрешением зависимостей |
| **rmmod** | Утилита для выгрузки модуля из ядра |
| **lsmod** | Утилита для отображения загруженных модулей |
| **modinfo** | Утилита для отображения информации о модуле |
| **depmod** | Утилита для генерации карты зависимостей модулей |
| **Module Signing** | Механизм подписи модулей для проверки подлинности |
| **LOCKDOWN LSM** | Механизм ограничения доступа к ядру (включая загрузку модулей) |
| **Secure Boot** | Механизм UEFI для проверки подписей загрузчика и ядра |

### Типы модулей

| Тип | Описание | Примеры |
| :--- | :--- | :--- |
| **Драйверы устройств** | Управление аппаратным обеспечением | `e1000`, `iwlwifi`, `nvidia` |
| **Файловые системы** | Поддержка новых ФС | `ntfs3`, `btrfs`, `exfat` |
| **Сетевые протоколы** | Реализация протоколов | `wireguard`, `openvswitch` |
| **Механизмы безопасности** | Расширения безопасности | `apparmor`, `selinux` |
| **Системные расширения** | Ядерные подсистемы | `vboxdrv`, `kvm`, `vfio` |

## Основные концепции

### Жизненный цикл модуля

1. **Сборка:** Компиляция исходного кода в объектный файл (`.ko`)
2. **Подпись:** Цифровая подпись модуля закрытым ключом
3. **Загрузка:** Загрузка модуля в адресное пространство ядра
4. **Инициализация:** Выполнение функции `module_init()`
5. **Эксплуатация:** Вызов функций модуля ядром
6. **Выгрузка:** Выполнение функции `module_exit()` и удаление из ядра

### Механизмы безопасности модулей

#### 1. Подпись модулей (Module Signing)

**Цель:** Предотвращение загрузки несанкционированных модулей.

**Реализация:**
- Ядро проверяет цифровую подпись при загрузке модуля
- Используется асимметричное шифрование (RSA/ECDSA)
- Ключи хранятся в ядре (встроенные) или на сервере подписи

**Режимы проверки:**
```
CONFIG_MODULE_SIG=y           # Включить подпись
CONFIG_MODULE_SIG_FORCE=y     # Принудительная проверка
CONFIG_MODULE_SIG_ALL=y       # Подписывать все модули
```

**Проверка подписи модуля:**
```bash
# Проверка подписи модуля
modinfo module.ko | grep signer

# Проверка, подписан ли модуль
modprobe --dump-modversions module.ko
```

**Последствия отсутствия подписи:**
- Модуль не загружается (при `CONFIG_MODULE_SIG_FORCE=y`)
- Предупреждение в логах ядра
- Отказ в загрузке на системах с Secure Boot

#### 2. Ограничение загрузки модулей (Module Blacklisting)

**Чёрный список модулей (blacklist):**
```bash
# /etc/modprobe.d/blacklist.conf
blacklist nouveau        # Отключить Nouveau (для NVIDIA)
blacklist usb-storage    # Отключить USB-накопители
blacklist floppy         # Отключить дисковод
```

**Блокировка через sysctl:**
```bash
# Запрет загрузки новых модулей
sysctl -w kernel.modules_disabled=1

# Проверка текущего значения
sysctl kernel.modules_disabled
```

**Примечание:** `kernel.modules_disabled=1` — необратимая операция до перезагрузки.

#### 3. LOCKDOWN LSM

**Механизм ограничения доступа к ядру** (начиная с ядра 5.4).

**Режимы:**
```bash
# Конфигурация ядра
CONFIG_SECURITY_LOCKDOWN_LSM=y
CONFIG_SECURITY_LOCKDOWN_LSM_EARLY=y

# Режимы (в файловой системе)
/sys/kernel/security/lockdown
```

**Режимы работы:**
- **None:** Нет ограничений
- **Integrity:** Запрет модификации ядра (включая загрузку модулей)
- **Confidentiality:** Запрет доступа к зашифрованным данным ядра

**Включение:**
```bash
# Через cmdline ядра
lockdown=confidentiality

# Проверка
cat /sys/kernel/security/lockdown
```

#### 4. Secure Boot

**Механизм UEFI** для проверки подписей загрузчика и ядра.

**Цепочка доверия:**
1. UEFI проверяет подпись загрузчика (shim или GRUB)
2. Загрузчик проверяет подпись ядра
3. Ядро проверяет подписи модулей

**Проверка Secure Boot:**
```bash
# Проверка состояния Secure Boot
mokutil --sb-state

# Или через sysfs
dmesg | grep -i "secure boot"
```

### Загрузка модулей

#### Автоматическая загрузка (systemd)

**systemd-modules-load.service:**
```bash
# /etc/modules-load.d/*.conf
# Формат: module_name [options]

# Примеры
br_netfilter
ip_tables
nfs
```

**Управление:**
```bash
# Перезагрузка модулей из конфигурации
systemctl restart systemd-modules-load

# Проверка загруженных модулей
systemctl status systemd-modules-load

# Просмотр логов
journalctl -u systemd-modules-load
```

#### Ручная загрузка

**insmod vs modprobe:**
```bash
# insmod: загрузка модуля без зависимостей
insmod /lib/modules/$(uname -r)/kernel/drivers/net/e1000/e1000.ko

# modprobe: загрузка с зависимостями
modprobe e1000

# modprobe с опциями
modprobe br_netfilter bridge二代目=1
```

**Выгрузка модулей:**
```bash
# Выгрузка модуля
rmmod module_name

# Выгрузка с зависимостями
modprobe -r module_name

# Проверка зависимости
modprobe --show-depends module_name
```

### Проверка модулей

**Просмотр информации:**
```bash
# Информация о модуле
modinfo module_name

# Зависимости модуля
modprobe --show-depends module_name

# Версия модуля
modinfo -F version module_name

# Автор и лицензия
modinfo -F author module_name
modinfo -F license module_name
```

**Проверка загруженных модулей:**
```bash
# Список загруженных модулей
lsmod

# Информация о конкретном модуле
lsmod | grep module_name

# Формат: Module | Used by | Size | Dependent modules
```

**Проверка модулей в /proc:**
```bash
# Информация о модулях
cat /proc/modules

# Статистика загрузки
cat /proc/sys/kernel/modules_disabled
```

## Практические сценарии

### Сценарий 1: Отключение ненужных модулей

**Цель:** Уменьшить поверхность атаки.

```bash
# 1. Определить ненужные модуleys
lsmod | grep -v -E '^(Module|ext4|xfs|nfs|bridge|veth|iptable)'

# 2. Создать blacklist
cat > /etc/modprobe.d/security-blacklist.conf << EOF
# Определение ненужных модулей
blacklist uvcvideo       # Веб-камера
blacklist snd            # Звук
blacklist bluetooth      # Bluetooth
blacklist garmin_gps     # GPS
blacklist cdc_acm        # USB-модемы
EOF

# 3. Перезагрузить модули
systemctl restart systemd-modules-load

# 4. Проверить
lsmod | grep -E 'uvcvideo|snd|bluetooth|garmin_gps|cdc_acm'
```

### Сценарий 2: Включение подписи модулей

**Цель:** Обеспечить аутентичность загружаемых модулей.

```bash
# 1. Проверить конфигурацию ядра
grep MODULE_SIG /boot/config-$(uname -r)

# 2. Если не включено, пересобрать ядро с опциями:
# CONFIG_MODULE_SIG=y
# CONFIG_MODULE_SIG_FORCE=y
# CONFIG_MODULE_SIG_ALL=y

# 3. Сгенерировать ключи подписи
cd /usr/src/linux-headers-$(uname -r)
make signing_keys.pem

# 4. Подписать модуль
scripts/sign-file sha256 signing_keys.pem signing_keys.x509 module.ko

# 5. Проверить подпись
modinfo module.ko | grep signer
```

### Сценарий 3: Блокировка загрузки модулей

**Цель:** Полная блокировка загрузки новых модулей.

```bash
# 1. Загрузить все необходимые модули
modprobe module1
modprobe module2

# 2. Заблокировать загрузку новых модулей
sysctl -w kernel.modules_disabled=1

# 3. Проверить
sysctl kernel.modules_disabled
# → 1

# 4. Попытка загрузки (должна завершиться ошибкой)
modprobe new_module
# → modprobe: ERROR: could not insert 'new_module': Operation not permitted
```

### Сценарий 4: Анализ модулей для безопасности

**Цель:** Проверить модули на наличие потенциальных уязвимостей.

```bash
# 1. Список загруженных модулей с деталями
lsmod | awk 'NR>1 {print $1}' | while read mod; do
  echo "=== $mod ==="
  modinfo $mod 2>/dev/null | grep -E '^(filename|license|author|vermagic)'
  echo ""
done

# 2. Поиск модулей без подписи
find /lib/modules/$(uname -r) -name "*.ko" -exec sh -c '
  modinfo "$1" 2>/dev/null | grep -q "signer" || echo "Unsigned: $1"
' _ {} \;

# 3. Проверка модулей на известные уязвимости
# (требуется дополнительная база данных CVE)

# 4. Анализ зависимостей
modprobe --show-depends module_name

# 5. Проверка лицензий
lsmod | awk 'NR>1 {print $1}' | while read mod; do
  license=$(modinfo -F license $mod 2>/dev/null)
  if [ "$license" != "GPL" ] && [ "$license" != "GPL v2" ]; then
    echo "Non-GPL module: $mod ($license)"
  fi
done
```

### Сценарий 5: Автоматическая загрузка модулей

**Цель:** Настроить автоматическую загрузку модулей при старте системы.

```bash
# 1. Создать конфигурационный файл
cat > /etc/modules-load.d/custom.conf << EOF
# Сетевые модули
br_netfilter
ip_tables
overlay

# Файловые системы
nfs
cifs

# Безопасность
apparmor
EOF

# 2. Перезагрузить службу
systemctl restart systemd-modules-load

# 3. Проверить
systemctl status systemd-modules-load

# 4. Проверить загруженные модули
lsmod | grep -E 'br_netfilter|ip_tables|overlay|nfs|cifs|apparmor'
```

## Дополнительная информация

### Современные тенденции

1. **Предпочтение встраивания в ядро:** Многие функции переносятся из модулей в основное ядро
2. **eBPF как замена модулям:** Для многих задач мониторинга и безопасности eBPF предпочтительнее модулей
3. **Усиление подписи:** Все больше дистрибутивов требуют подписи модулей
4. **Ограничение rootkit:** Механизмы secure boot и lockdown LSM затрудняют установку rootkit

### Сравнение с другими механизмами безопасности

| Механизм | Уровень | Применение | Overhead |
| :--- | :--- | :--- | :--- |
| **Module Signing** | Ядро | Аутентичность модулей | Минимальный |
| **LOCKDOWN LSM** | Ядро | Ограничение доступа к ядру | Минимальный |
| **Secure Boot** | UEFI/Ядро | Цепочка доверия загрузки | Нулевой (при загрузке) |
| **Seccomp** | Ядро | Фильтрация системных вызовов | Низкий |
| **AppArmor/SELinux** | Ядро | Контроль доступа | Низкий-средний |

### Интеграция с DevOps/CI/CD

```bash
# Проверка модулей в CI-pipeline
#!/bin/bash
set -e

# Проверка отсутствия небезопасных модулей
FORBIDDEN_MODULES=("usb-storage" "floppy" "udf")
for mod in "${FORBIDDEN_MODULES[@]}"; do
  if lsmod | grep -q "$mod"; then
    echo "ERROR: Forbidden module loaded: $mod"
    exit 1
  fi
done

# Проверка подписи модулей
find /lib/modules/$(uname -r) -name "*.ko" | while read mod; do
  if ! modinfo "$mod" 2>/dev/null | grep -q "signer"; then
    echo "WARNING: Unsigned module found: $mod"
  fi
done

echo "Module security check passed"
```

### Автоматизация с Ansible

```yaml
---
# Роль для управления модулями ядра
- name: Управление модулями ядра
  hosts: all
  become: yes
  tasks:
    - name: Отключение ненужных модулей
      modprobe:
        name: "{{ item }}"
        state: absent
      loop:
        - uvcvideo
        - snd
        - bluetooth
      tags: blacklist

    - name: Загрузка необходимых модулей
      modprobe:
        name: "{{ item }}"
        state: present
      loop:
        - br_netfilter
        - ip_tables
        - overlay
      tags: load

    - name: Блокировка загрузки модулей
      sysctl:
        name: kernel.modules_disabled
        value: '1'
        sysctl_set: yes
        state: present
      when: lockdown_modules | default(false)
      tags: lockdown
```

### Типичные ошибки

1. **Отсутствие подписи:** Модули не загружаются на системах с Secure Boot
2. **Неправильный порядок:** Загрузка модуля до его зависимостей
3. **Игнорирование blacklist:** Попытка загрузить заблокированный модуль
4. **Забывание выгрузки:** Модуль остаётся в памяти после использования
5. **Отсутствие проверки:** Непроверенные модули из сторонних репозиториев