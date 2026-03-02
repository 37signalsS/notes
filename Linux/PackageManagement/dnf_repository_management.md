# Управление репозиториями в DNF

## Практические сценарии

### Просмотр репозиториев

```bash
# Список репозиториев (включенные и отключенные)
dnf repolist all

# Подробная информация о репозитории
dnf repoinfo <repo_id>

# Включить/отключить репозиторий временно
sudo dnf config-manager --set-enabled <repo_id>
sudo dnf config-manager --set-disabled <repo_id>
```

### Файлы репозиториев

Конфигурационные файлы репозиториев находятся в директории `/etc/yum.repos.d/` и имеют расширение `.repo`.

**Структура файла:**

```ini
[repo_id]                    # Идентификатор репозитория
name=Repository Name         # Человекочитаемое имя
baseurl=http://...           # URL репозитория (или mirrorlist=)
enabled=1                    # Включен (1) или выключен (0)
gpgcheck=1                   # Проверка GPG-подписи (0 - выкл)
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY   # Путь к публичному ключу
cost=1000                    # Приоритет (меньше = выше приоритет)
```

### Добавление GPG-ключа

Для защиты от MitM-атак репозитории и пакеты подписываются GPG-ключами.

```bash
# Импортировать ключ в систему
sudo rpm --import /path/to/gpg-key.pub

# Импортировать ключ напрямую из URL
sudo rpm --import https://example.com/gpg-key.pub
```

### Создание локального репозитория

Подробное руководство по созданию зеркала репозитория доступно в заметке: [Локальное зеркало репозитория](./local_repository_mirror.md).

---

См. также: [Обзор управления пакетами в Linux](./linux_package_management_overview.md)
