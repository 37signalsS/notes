# Безопасность LVM: шифрование, контроль доступа и аудит

## Определения

**LUKS (Linux Unified Key Setup)** — стандарт шифрования блочных устройств в Linux. Работает на уровне device-mapper (dm-crypt), обеспечивая прозрачное шифрование данных на LV. LUKS2 — текущая версия с поддержкой AEAD-алгоритмов (AES-GCM, AES-XTS).

**dm-crypt** — подсистема ядра Linux для шифрования блочных устройств через device-mapper. LUKS — пользовательский интерфейс для управления dm-crypt.

**PV Encryption** — шифрование физического тома LVM. Позволяет шифровать все LV в VG единым ключом, но требует ввода пароля при каждой загрузке (или ключа в initramfs).

**LV Encryption** — шифрование отдельного LV поверх существующего VG. Более гибко: позволяет шифровать только критичные тома (например, БД), не затрагивая системные.

**Key File** — файл, содержащий ключ шифрования. Позволяет автоматически раскрывать LUKS-контейнер без интерактивного ввода пароля (для серверов). Должен быть защищён (permissions 0400, ownership root:root).

**Clevis/Tang** — framework для автоматического раскрытия LUKS без пароля через привязку к TPM, HTTP-серверу (Tang) или другому机制. Используется в automate decryption для серверов.

**auditd** — система аудита Linux, фиксирующая системные вызовы и безопасность. Может мониторить команды LVM для обнаружения несанкционированных изменений.

## Базовые концепции

### Уровни шифрования LVM

```
┌─────────────────────────────────────────────┐
│  Уровень 1: Файловая система (fscrypt)      │  ← Шифрование отдельных файлов
├─────────────────────────────────────────────┤
│  Уровень 2: LV (dm-crypt)                   │  ← Шифрование отдельного LV
├─────────────────────────────────────────────┤
│  Уровень 3: PV (dm-crypt поверх PV)         │  ← Шифрование всех LV в VG
├─────────────────────────────────────────────┤
│  Уровень 4: Диск (SED/ hardware encryption) │  ← Аппаратное шифрование
└─────────────────────────────────────────────┘
```

### Сравнение подходов

| Подход | Гибкость | Безопасность | Автоматизация | Overhead |
|:---|:---|:---|:---|:---|
| **LUKS на LV** | Высокая (только нужные LV) | Высокая | Средняя (нужен key file или Tang) | Средний (~5-10%) |
| **LUKS на PV** | Низкая (все LV в VG) | Максимальная | Средняя | Средний |
| **LUKS на整个 диск** | Низкая | Максимальная | Низкая (пароль при загрузке) | Минимальный |
| **fscrypt** | Очень высокая (файлы) | Средняя | Низкая | Низкий |

## Практические сценарии

### Шаг 1: Шифрование LV через LUKS

```bash
# Создание LV (обычно)
sudo lvcreate -L 200G -n lv_secret vg_data

# Шифрование LV
sudo cryptsetup luksFormat /dev/vg_data/lv_secret
# → Ввести пароль дважды

# Раскрытие (открытие) контейнера
sudo cryptsetup luksOpen /dev/vg_data/lv_secret secret_lv
# → Ввести пароль

# Создание ФС на раскрытом контейнере
sudo mkfs.xfs /dev/mapper/secret_lv

# Монтирование
sudo mkdir -p /mnt/secret
sudo mount /dev/mapper/secret_lv /mnt/secret

# Проверка
lsblk
# → vg_data-lv_secret  200G
#   └─secret_lv        200G  crypt /mnt/secret
```

### Шаг 2: Автоматическое раскрытие через key file

```bash
# Создание key file (на сервере)
sudo dd if=/dev/urandom of=/root/.luks_key bs=1 count=256
sudo chmod 400 /root/.luks_key
sudo chown root:root /root/.luks_key

# Добавление key file в LUKS
sudo cryptsetup luksAddKey /dev/vg_data/lv_secret /root/.luks_key
# → Ввести существующий пароль

# Проверка наличия key file
sudo cryptsetup luksDump /dev/vg_data/lv_secret | grep "Key Slot"
# → Key Slot 0: ENABLED (пароль)
# → Key Slot 1: ENABLED (key file)

# Автоматическое раскрытие в initramfs (Debian/Ubuntu)
echo "secret_lv /dev/vg_data/lv_secret /root/.luks_key luks" | \
  sudo tee -a /etc/crypttab

# Обновление initramfs
sudo update-initramfs -u
```

### Шаг 3: Шифрование через Clevis + Tang (автоматизация)

```bash
# Установка Clevis
sudo apt install clevis clevis-luks clevis-systemd  # Debian/Ubuntu
sudo dnf install clevis clevis-luks clevis-dracut    # RHEL/Fedora

# Привязка LUKS-контейнера к Tang-серверу
sudo clevis luks bind -d /dev/vg_data/lv_secret \
  tang '{"url":"http://tang.example.com:7500"}'

# Проверка
sudo clevis luks list -d /dev/vg_data/lv_secret
# → 0: systemd (NVMe, если есть)
# → 1: tang ["http://tang.example.com:7500"]

# Включение автоматического раскрытия
sudo systemctl enable clevis-luks-askpass.path

# Перезагрузка для тестирования
sudo reboot
# → Контейнер раскроется автоматически при доступности Tang-сервера
```

### Шаг 4: Аудит команд LVM

```bash
# Создание правил аудита
sudo auditctl -w /usr/sbin/lvremove -p x -k lvm_lvremove
sudo auditctl -w /usr/sbin/lvchange -p x -k lvm_lvchange
sudo auditctl -w /usr/sbin/vgremove -p x -k lvm_vgremove
sudo auditctl -w /usr/sbin/pvremove -p x -k lvm_pvremove
sudo auditctl -w /usr/sbin/vgcreate -p x -k lvm_vgcreate
sudo auditctl -w /usr/sbin/vgextend -p x -k lvm_vgextend

# Сохранение правил
sudo auditctl -l > /etc/audit/rules.d/lvm.rules

# Просмотр аудит-логов
sudo ausearch -k lvm_lvremove
# → type=PROCTITLE ... proctitle="/usr/sbin/lvremove /dev/vg_data/lv_old"
# → type=USER_CMD ... cmd="lvremove /dev/vg_data/lv_old"
```

### Шаг 5: Защита доступа к LVM

```bash
# Ограничение доступа к утилитам LVM
sudo chmod 700 /usr/sbin/lv*
sudo chmod 700 /usr/sbin/pv*
sudo chmod 700 /usr/sbin/vg*

# Настройка PAM для логирования LVM-команд
# /etc/pam.d/lvm (создать файл):
# auth    required    pam_log_session.so
# session required    pam_log_session.so

# Проверка ownership /etc/lvm
ls -la /etc/lvm/
# → drwx------ root root ... lvm.conf
# → drwx------ root root ... backup/
# → drwx------ root root ... archive/

# Блокировка изменения lvm.conf
sudo chattr +i /etc/lvm/lvm.conf
# → (только для максимально критичных систем)
```

### Шаг 6: Проверка целостности метаданных

```bash
# Регулярная проверка (cron job)
sudo vgck --reportformat json vg_data

# Проверка всех VG
for vg in $(sudo vgs --noheadings -o vg_name); do
    if ! sudo vgck "$vg" >/dev/null 2>&1; then
        echo "ALERT: $vg metadata check FAILED"
        # Отправка алерта (slack, email, etc.)
    fi
done

# Сравнение текущих метаданных с backup
sudo vgcfgrestore --test vg_data
```

## Дополнительная информация

### Типичные ошибки

| Симптом | Причина | Решение |
|:---|:---|:---|
| `No key available` | Key file повреждён или удалён | Восстановить из backup, использовать резервный пароль |
| `LUKS header corrupt` | Повреждение заголовка LUKS | Восстановить из `cryptsetup luksHeaderBackup` |
| `Device is busy` | LV используется процессом | `lsof /dev/mapper/secret_lv`, `fuser -km /mnt/secret` |
| `Clevis: tang server unreachable` | Нет доступа к Tang-серверу | Проверить сеть, использовать fallback-пароль |

### Best Practices

1. **Резервное копирование LUKS-заголовка:** Всегда делайте `cryptsetup luksHeaderBackup` и храните копию на защищённом носителе.
2. **Минимизация шифрования:** Шифруйте только критичные данные (БД, секреты), не системные LV — это упрощает восстановление.
3. **Key file protection:** Храните key file на защищённом носителе (USB, TPM), не на основном диске.
4. **Тестирование раскрытия:** Регулярно проверяйте автоматическое раскрытие (Clevis/Tang) после обновлений.
5. **Аудит:** Настройте `auditd` для мониторинга команд LVM и cryptsetup.

### См. также
- **[LUKS и шифрование](../../Core/cryptsetup_luks.md)** — полное руководство по LUKS2.
- **[LVM — Thin Provisioning](../thin-provisioning.md)** — комбинирование шифрования и thin provisioning.
- **[LVM — Управление](../management_operations.md)** — мониторинг и метрики.
