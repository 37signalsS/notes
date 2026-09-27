# Определения

**Autofs** — системная служба Linux для автоматического монтирования файловых систем по требованию. 

В отличие от статического монтирования через `/etc/fstab`, Autofs подключает ресурс только в момент обращения процесса к соответствующей директории и автоматически размонтирует его после заданного периода неактивности. Это критически важно для экономии сетевых ресурсов и предотвращения зависаний системы при недоступности удаленных серверов.

> **Статус технологии:** Autofs версии 5.x остается стандартом для сложных корпоративных сред. Несмотря на наличие `systemd automount`, Autofs предпочтительнее для сценариев с использованием wildcard-карт, интеграции с LDAP/SSSD и управления тысячами точек монтирования.

# Основные концепции

## Архитектура конфигурации

Работа Autofs базируется на иерархии файлов:

1.  **Главный файл (`/etc/auto.master`)**: Определяет базовые точки монтирования и связывает их с файлами карт.
2.  **Файлы карт (Maps)**: Содержат списки поддиректорий, опции и источники данных.
3.  **Исполняемые карты (Executable Maps)**: Скрипты, генерирующие параметры монтирования динамически.

## Использование переменных в картах

Autofs поддерживает системные переменные, что позволяет создавать универсальные карты для различных архитектур и хостов:
*   `${ARCH}` — архитектура системы (например, `x86_64`).
*   `${HOST}` — имя хоста.
*   `${OSNAME}` — название ОС (обычно `linux`).
*   `${OSREL}` — версия релиза.

Пример использования: `*  -rw,soft  server:/export/&/${ARCH}`

## Режимы отображения (Browsing)

*   **Ghosting (`--ghost` или `browse`)**: Создает пустые директории-плейсхолдеры. Пользователь видит все возможные точки монтирования в `ls`.
    *   *Плюс:* Удобство навигации.
    *   *Минус:* При тысячах ключей в LDAP это вызывает значительную нагрузку на VFS и замедляет листинг родительского каталога.
*   **Non-browsable (по умолчанию)**: Директории появляются только при обращении по точному имени.

## Таймауты и политика повторов

Ключевые параметры для управления поведением при недоступности сервера:

| Параметр | Назначение | Рекомендация для SRE |
| :--- | :--- | :--- |
| `--timeout=N` | Время неактивности (секунды) перед размонтированием | `300`–`600` для домашних директорий; `60`–`120` для временных ресурсов |
| `--ghost` | Создание плейсхолдеров | Отключить при >1000 ключей LDAP |
| `soft` | Возврат ошибки после таймаута вместо бесконечного повтора | Использовать для NFS с `timeo=50,retrans=2` |
| `hard` | Бесконечный повтор запроса (процесс блокируется) | Использовать для критичных данных, где важна целостность |
| `intr` / `nointr` | Разрешение прерывания зависших запросов | `nointr` по умолчанию в современных ядрах |
| `_netdev` | Откладывает монтирование до поднятия сети | **Обязательно** для всех сетевых ФС |
| `nofail` | Не прерывает загрузку при ошибке монтирования | **Обязательно** для autofs в fstab |
| `actimeo=N` | TTL кэша атрибутов (секунды) | `60`–`300` для снижения нагрузки на сервер |

> **Важное замечание:** Параметр `soft` в сочетании с `timeo` и `retrans` предотвращает зависание процессов при недоступности NFS-сервера. Однако для критичных данных предпочтительнее `hard`, так как `soft` может привести к порче данных при сетевых сбоях.

# Практические сценарии

## Подготовка окружения

### Установка пакетов

**Debian/Ubuntu:**
```bash
sudo apt update && sudo apt install -y autofs nfs-common
# → success
```

**RHEL/CentOS/Rocky:**
```bash
sudo dnf install -y autofs nfs-utils
# → success
```

### Включение и запуск службы

```bash
sudo systemctl enable --now autofs
# → Created symlink /etc/systemd/system/multi-user.target.wants/autofs.service
# → success
```

### Проверка статуса

```bash
sudo systemctl status autofs
# → ● autofs.service - Automounts filesystems on demand
# →    Loaded: loaded (/lib/systemd/system/autofs.service; enabled)
# →    Active: active (running) since ...
```

## Сценарий 1: Динамические домашние директории (NFS)

Стандартное решение, где данные пользователя «следуют» за ним.

**Конфигурация `/etc/auto.master`:**
```text
/home  /etc/auto.home  --timeout=600 --ghost
```

**Карта `/etc/auto.home`:**
```text
# Использование wildcard (*) и подстановки ключа (&)
*  -rw,soft,intr,nosuid,nodev,_netdev  nfsserver.local:/export/home/&
```

**Объяснение опций:**
*   `-rw` — чтение и запись
*   `soft` — возврат ошибки при недоступности сервера
*   `intr` — устарело, оставлено для совместимости
*   `nosuid` — запрет выполнения бинарных файлов с SUID-битом
*   `nodev` — запрет интерпретации устройств в ФС
*   `_netdev` — отложить монтирование до готовности сети

## Сценарий 2: Multi-mount (Групповое монтирование)

Один ключ активирует монтирование нескольких ресурсов в поддиректории.

**Карта `/etc/auto.projects`:**
```text
# При обращении к /projects/my_project смонтируются три ресурса
my_project \
    /src   -rw,soft,_netdev  srv1:/data/src/& \
    /bin   -ro,soft,_netdev  srv2:/data/bin/& \
    /docs  -rw,soft,_netdev  srv1:/data/docs/&
```

## Сценарий 3: Прямое монтирование (Absolute Paths)

Позволяет монтировать ресурсы в произвольные места системы без общего родительского каталога.

**Конфигурация `/etc/auto.master`:**
```text
/-  /etc/auto.direct  --timeout=60
```

**Карта `/etc/auto.direct`:**
```text
/var/www/static  -fstype=nfs4,ro,soft,_netdev  assets.local:/www/static
/opt/tools       -fstype=nfs4,rw,soft,_netdev  tools.local:/common/tools
```

> **Примечание:** При использовании `fstype=nfs4` явное указание версии протокола повышает стабильность. Для NFSv4 также рекомендуется добавить `noatime` для снижения нагрузки на метаданные.

## Сценарий 4: Монтирование SMB/CIFS ресурсов

Autofs также поддерживает монтирование Windows-шаров и Samba-ресурсов.

**Карта `/etc/auto.smb`:**
```text
# Монтирование CIFS-ресурса с аутентификацией
# Учетные данные хранятся в /etc/auto.smb.secrets (chmod 600)
share  -fstype=cifs,rw,soft,_netdev,credentials=/etc/auto.smb.secrets  ://fileserver.local/share
```

**Файл `/etc/auto.smb.secrets`:**
```text
username=srv_account
password=SecurePass123
domain=EXAMPLE
```

**Настройка `/etc/auto.master`:**
```text
/mnt/smb  /etc/auto.smb  --timeout=300
```

**Права доступа:**
```bash
sudo chmod 600 /etc/auto.smb.secrets
# → только root может читать файл с учетными данными
```

> **Безопасность:** Никогда не храните пароли в открытом виде в картах. Используйте файл `credentials` с правами `600`.

## Сценарий 5: Интеграция с SSSD и LDAP

Централизованное управление картами для тысяч серверов.

1.  **Настройка `/etc/sssd/sssd.conf`**:
    ```ini
    [sssd]
    services = nss, pam, autofs
    
    [autofs]
    # Настройки кэширования
    ```
2.  **Настройка `/etc/nsswitch.conf`**:
    ```text
    automount: files sss
    ```

## Сценарий 6: Исполняемые карты (Executable Maps)

Для сложных условий монтирования используйте скрипты, генерирующие параметры динамически.

**Конфигурация `/etc/auto.master`:**
```text
/mnt/exec  /etc/auto.exec  --timeout=60
```

**Скрипт `/etc/auto.exec` (должен быть исполняемым: chmod 755):**
```bash
#!/bin/bash
# Формат вывода: ключ [опции] источник
# Пример: монтировать только для определенных хостов

case "$HOST" in
    web-*)
        echo "projects -ro,soft,_netdev web-srv:/data/&"
        ;;
    db-*)
        echo "projects -rw,soft,_netdev db-srv:/data/&"
        ;;
    *)
        echo "- & not found"
        ;;
esac
```

**Объяснение:**
*   `echo "- & not found"` — возвращает ошибку для неизвестных ключей
*   `&` — подстановка запрошенного ключа в путь
*   Скрипт должен завершаться быстро (<1 секунды), иначе autofs вернет ошибку

## Сценарий 7: Wildcard-карты для временных ресурсов

Монтирование ресурсов с динамическими именами (например, snapshot'ы).

**Карта `/etc/auto.snapshots`:**
```text
# Монтирование snapshot'ов по шаблону
snap-*  -fstype=nfs4,ro,soft,_netdev  backup.local:/snapshots/&
```

**Использование:**
```bash
ls /mnt/snapshots/snap-20240101
# → trigger mount
```

# Валидация и тестирование

## Проверка конфигурации

Перед применением всегда проверяйте синтаксис:

```bash
# Проверка синтаксиса auto.master
sudo automount --test
# → любая ошибка парсинга будет выведена в stderr

# Проверка конкретной карты
sudo automount --test --map /etc/auto.home
```

## Тестирование без физического replugging

```bash
# Принудительный trigger для тестирования монтирования
sudo systemctl restart autofs
# Проверка, что демон поднялся без ошибок
sudo systemctl status autofs

# Попытка обращения к точке монтирования
ls /home/testuser
# → должен произойти mount

# Проверка результата
findmnt -t autofs
# → /home/home/testuser autofs rw,relatime,vers=4.2,...

# Проверка journal
journalctl -u autofs -e
# → последние события демона
```

## Проверка timeout и размонтирования

```bash
# Обратитесь к смонтированной директории
ls /home/testuser

# Дождитесь timeout (по умолчанию 600 секунд)
# Или принудительно проверьте статус
findmnt -t autofs
# → точка должна исчезнуть после timeout
```

## Проверка SELinux (RHEL/CentOS)

Если на клиенте включен SELinux, убедитесь, что контексты允许вают работу autofs:

```bash
# Проверка текущего контекста autofs
sudo ls -Z /etc/auto.master
# → system_u:object_r:etc_t:s0 /etc/auto.master

# Проверка блокировок в audit log
sudo ausearch -m avc -ts recent | grep autofs
# → при необходимости: sudo restorecon /etc/auto.master
```

# Диагностика и отладка

### Интерактивная отладка

Если монтирование не происходит, запустите демон в режиме foreground с логированием в консоль:
```bash
sudo systemctl stop autofs
sudo automount -f -v
# → перехватывает попытки обращения и выводит ошибки парсинга карт
```

### Мониторинг и анализ

*   **Журнал:** `journalctl -u autofs -f`
*   **VFS статус:** `findmnt -t autofs` (показывает управляющие точки)
*   **Проверка ключей:** `autofs-ldap-auth-config` (для отладки LDAP соединений)
*   **Статистика NFS:** `nfsstat -m` (после монтирования)
*   **Проверка экспортов:** `showmount -e nfsserver.local`

### Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `automount: bad option "soft"` | Неправильный синтаксис в карте | Проверьте, что опции разделены запятыми, опция указана перед источником |
| `mount: wrong fs type` | Отсутствует пакет `nfs-common` или `cifs-utils` | `sudo apt install nfs-common cifs-utils` |
| `RPC: Program not registered` | Сервер не экспортирует директорию или не запущен `rpcbind` | Проверьте `exportfs -v` на сервере |
| `Stale file handle` | Экспорт удален на сервере, но кэш клиента устарел | `sudo exportfs -ra` на сервере; перезапуск autofs на клиенте |
| `Permission denied` | Несовпадение UID/GID или `root_squash` | Проверьте `/etc/idmapd.conf` и опции экспорта |
| `No such file or directory` при обращении | Точка монтирования не создана | Autofs создает точки автоматически; проверьте права на родительский каталог |

## Мониторинг и алертинг в production

```bash
# Поиск ошибок монтирования за последний час
journalctl -u autofs --since "1 hour ago" | grep -i "error\|fail\|timeout"

# Мониторинг stale NFS-монтирований
findmnt -t nfs -o TARGET,SOURCE,FSTYPE,OPTIONS | grep -v "^TARGET"

# Проверка доступности NFS-серверов (скрипт)
for server in nfssrv1 nfssrv2; do
    showmount -e $server > /dev/null 2>&1 && echo "$server OK" || echo "$server FAIL"
done
```

# Ограничения и риски

| Риск | Описание | Решение |
| :--- | :--- | :--- |
| **Stale Mounts** | Сервер упал, точка монтирования зависла. | Использовать `soft,timeo=50,retrans=2`. |
| **Recursive Scans** | Утилиты типа `updatedb` или `du` вызывают монтирование всего. | Исключать пути autofs из сканирования. |
| **Negative Caching** | Autofs кэширует ошибку поиска ключа. | Настройка `negative_timeout` (по умолчанию 60с). |
| **Конфликты с systemd** | Два механизма автомонтирования для одного пути | Использовать либо autofs, либо systemd automount, но не оба одновременно |
| **Зависание при hard монтировании** | При `hard` процессы уходят в состояние `D` | Использовать `soft` или `hard,intr` (устарело) |
| **Утечка учетных данных** | Пароли в файлах `credentials` | Права `600`, включение `chroot` в sshd для SFTP-доступа |

## Защита от рекурсивного сканирования

В `/etc/updatedb.conf` добавьте autofs-пути в `PRUNEFS` и `PRUNEPATHS`:

```text
PRUNEFS="NFS nfsfs CIFS autofs iso9660 ncpfs coda devpts efivarfs"
PRUNEPATHS="/home /mnt/autofs"
```

# Управление конфигурацией (Ansible)

Для массового развертывания используйте модуль `ansible.builtin.template`:

```yaml
---
- name: Deploy Autofs configuration
  hosts: all
  become: true
  tasks:
    - name: Install autofs and nfs-common
      ansible.builtin.apt:
        name:
          - autofs
          - nfs-common
        state: present
      when: ansible_os_family == "Debian"

    - name: Install autofs and nfs-utils (RHEL)
      ansible.builtin.dnf:
        name:
          - autofs
          - nfs-utils
        state: present
      when: ansible_os_family == "RedHat"

    - name: Deploy auto.master
      ansible.builtin.template:
        src: templates/auto.master.j2
        dest: /etc/auto.master
        owner: root
        group: root
        mode: '0644'
      notify: Reload autofs

    - name: Deploy auto.home
      ansible.builtin.template:
        src: templates/auto.home.j2
        dest: /etc/auto.home
        owner: root
        group: root
        mode: '0644'
      notify: Reload autofs

    - name: Ensure autofs is running and enabled
      ansible.builtin.systemd:
        name: autofs
        state: started
        enabled: true

  handlers:
    - name: Reload autofs
      ansible.builtin.systemd:
        name: autofs
        state: reloaded
```

**Шаблон `templates/auto.master.j2`:**
```jinja2
# AutoFS master map
# Generated by Ansible - do not edit manually

/home  /etc/auto.home  --timeout=600 --ghost
/-  /etc/auto.direct  --timeout=60
/mnt/smb  /etc/auto.smb  --timeout=300
```

> **Правило:** Всегда используйте шаблоны и уведомления (`notify`) для перезагрузки autofs после изменения конфигурации.

# Практические рекомендации для SRE

*   **Идемпотентность:** Автоматизируйте развертывание через Ansible/Puppet/Chef. Никаких ручных редактирований.
*   **Резервное копирование:** Сохраняйте версии `/etc/auto.master` и всех карт в Git.
*   **Таймауты:** Настраивайте `--timeout` с запасом. Слишком короткий таймаут вызывает "моргание" при кратковременном простое.
*   **Логирование:** Настройте централизованный сбор логов `journalctl -u autofs` через ELK/Graylog.
*   **Документация:** Ведите реестр всех точек монтирования с указанием владельца, SLA и escalation-цепочки.
*   **Тестирование:** Перед внесением изменений в production тестируйте на staging-сервере с аналогичной конфигурацией.
*   **Мониторинг:** Добавьте проверки на `findmnt -t autofs` и `systemctl is-active autofs` в ваши health-checks.
*   **Аудит:** Регулярно проверяйте `/etc/auto.master` и карты на наличие устаревших записей (отключенные серверы, уволенные сотрудники).

# Очистка и удаление правил

Для удаления точки монтирования Autofs:

1.  **Удалите соответствующую строку из `/etc/auto.master`.**
2.  **Удалите или закомментируйте карту.**
3.  **Перезапустите службу:**
    ```bash
    sudo systemctl restart autofs
    ```
4.  **Принудительно размонтируйте зависшие точки:**
    ```bash
    sudo umount -l /path/to/mount
    # → ленивое размонтирование (очистка после закрытия дескрипторов)
    ```

# Дополнительная информация

*   **[Протокол NFS](../../../Networking/Services/nfs/index.md)** — параметры производительности.
*   **[Systemd Mount Units](./systemd_mount.md)** — альтернатива для простых задач.
*   **[Команды монтирования](../commands.md)** — диагностика через `findmnt`.
*   **[NFS: Настройка сервера и клиента](../../../Networking/Services/nfs/nfs_setup.md)** — экспорт и монтирование NFS.
