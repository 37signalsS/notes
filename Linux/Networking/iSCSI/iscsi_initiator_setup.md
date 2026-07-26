# iSCSI: Настройка инициатора (Клиент)

> **Надёжность: 10/10** (Проверено на Debian 12, Ubuntu 24.04, RHEL 9)
> **Актуальность: 2026-07** (Версия open-iscsi 2.1.10+)

**iSCSI Initiator (Инициатор)** — клиентское программное обеспечение или аппаратный адаптер, который инициирует сессии обмена данными с удаленными хранилищами (таргетами). В Linux стандартным стеком является **open-iscsi**, который представляет удаленные LUN как обычные локальные блочные устройства (/dev/sdX).

## Определения

| Термин | Описание |
| :--- | :--- |
| **Iscsid** | Фоновый демон, управляющий iSCSI-соединениями и восстанавливающий сессии после сбоев. |
| **Iscsiadm** | Утилита командной строки для управления базами данных discovery, узлов и сессий. |
| **Node (Узел)** | Запись в локальной базе данных инициатора, содержащая параметры подключения к конкретному таргету. |
| **Session (Сессия)** | Активное TCP-соединение между инициатором и порталом таргета. |
| **Discovery** | Процесс опроса портала для получения списка доступных на нем таргетов. |

## Основные концепции

Теоретическая база (IQN, порталы, LUN) подробно изложена в документе **[Основные концепции iSCSI](./iscsi_concepts.md)**. Перед началом настройки на стороне клиента должны быть известны:
- IP-адрес и порт таргета (обычно 3260).
- IQN таргета.
- Учетные данные CHAP (если используются).

## Практические сценарии

### 1. Установка и идентификация

#### Установка пакетов
```bash
sudo apt update && sudo apt install open-iscsi -y
# Для RHEL/CentOS/Rocky: sudo dnf install iscsi-initiator-utils -y
```

#### Настройка имени инициатора
Имя инициатора должно быть уникальным. Отредактируйте `/etc/iscsi/initiatorname.iscsi`:
```bash
# Пример содержимого
InitiatorName=iqn.2026-07.com.example:client.node01
```
После изменения перезапустите службу:
```bash
sudo systemctl restart iscsid open-iscsi
```

### 2. Подключение к хранилищу

#### Обнаружение таргетов (Discovery)
```bash
sudo iscsiadm -m discovery -t sendtargets -p <IP_TARGET>
# → 192.168.1.10:3260,1 iqn.2026-07.com.example:storage.target01
```

#### Вход в систему (Login)
```bash
# Подключить конкретный таргет
sudo iscsiadm -m node -T <IQN_TARGET> -p <IP_TARGET> --login

# Подключить все обнаруженные таргеты
sudo iscsiadm -m node --loginall=all
```

#### Настройка автоматического подключения
Для сохранения сессии после перезагрузки:
```bash
sudo iscsiadm -m node -T <IQN_TARGET> -p <IP_TARGET> -o update -n node.startup -v automatic
```

### 3. Работа с дисками и монтирование

#### Поиск нового устройства
```bash
lsblk --scsi
# → sdb      8:16   0   100G  0 disk
```

#### Сканирование новых LUN (без перезахода)
Если на таргете были добавлены новые LUN в существующую сессию:
```bash
sudo iscsiadm -m session --rescan
```

#### Постоянное монтирование (/etc/fstab)
**Обязательно** используйте опцию `_netdev`, чтобы система не пыталась монтировать диск до инициализации сети.
```text
# Рекомендуемый формат в /etc/fstab
UUID=xxxx-xxxx  /mnt/iscsi_disk  ext4  _netdev,nofail,x-systemd.device-timeout=30s  0  2
```

### 4. Настройка CHAP аутентификации

Если таргет требует авторизацию, обновите параметры узла:
```bash
sudo iscsiadm -m node -T <IQN> -p <IP> -o update -n node.session.auth.authmethod -v CHAP
sudo iscsiadm -m node -T <IQN> -p <IP> -o update -n node.session.auth.username -v <USER>
sudo iscsiadm -m node -T <IQN> -p <IP> -o update -n node.session.auth.password -v <PASS>
```

## Дополнительная информация

### Диагностика и управление

| Задача | Команда |
| :--- | :--- |
| Список активных сессий | `iscsiadm -m session` |
| Подробный статус (LUN, пути) | `iscsiadm -m session -P 3` |
| Просмотр базы данных узлов | `iscsiadm -m node` |
| Выход из системы (Logout) | `iscsiadm -m node -T <IQN> -p <IP> --logout` |
| Удаление узла из базы | `iscsiadm -m node -T <IQN> -p <IP> -o delete` |

### Типичные проблемы

1.  **Зависание при загрузке**: Проверьте наличие `_netdev` в `fstab`. Без этого `systemd` заблокирует загрузку, ожидая локальный диск, который требует сети.
2.  **Таймауты сессий**: При высокой нагрузке на сеть может потребоваться увеличение `node.session.timeo.replacement_timeout` в `/etc/iscsi/iscsid.conf`.
3.  **Discovery не находит таргет**: Проверьте порт 3260/tcp на таргете и убедитесь, что в ACL таргета добавлен актуальный IQN инициатора.

### См. также

- **[Основные концепции iSCSI](./iscsi_concepts.md)** — архитектура и терминология.
- **[Настройка iSCSI Target (Сервер)](./iscsi_target_setup.md)** — создание и экспорт LUN.
- **[Настройка Multipath I/O](./iscsi_multipath.md)** — объединение путей для отказоустойчивости.
- **[Оптимизация производительности iSCSI](./iscsi_performance.md)** — тюнинг сетевого стека.
- **[Управление томами LVM](../../FileSystems/LVM/operations/lvm_disk_replacement.md)** — работа с VG поверх iSCSI.
