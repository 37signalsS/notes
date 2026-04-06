# Сборка пакетов: Дополнительная информация

## Продвинутые техники

### Чистое окружение для сборки

Использование изолированных окружений гарантирует воспроизводимость сборки и отсутствие скрытых зависимостей ([основные понятия сборки](./basic_concepts.md)).

**DEB: pbuilder**

```bash
# Установка
sudo apt-get install pbuilder debootstrap

# Создание базового окружения
sudo pbuilder create --distribution focal

# Сборка в чистом окружении
sudo pbuilder build ../package-name_version.dsc

# Результат в /var/cache/pbuilder/result/
```

**RPM: mock**

```bash
# Установка
sudo dnf install mock

# Добавление пользователя в группу mock
sudo usermod -aG mock $USER

# Сборка для Fedora 38 x86_64
mock -r fedora-38-x86_64 ~/rpmbuild/SRPMS/package-name.src.rpm

# Результат в /var/lib/mock/fedora-38-x86_64/result/
```

### Кросс-компиляция

Сборка пакетов для архитектуры, отличной от хостовой:

```bash
# DEB: Сборка для другой архитектуры
dpkg-buildpackage -aarm64 -us -uc

# RPM: Сборка для другой архитектуры
rpmbuild --target=aarch64 -ba SPECS/package.spec
```

### Автоматизация с CI/CD

Интеграция сборки пакетов в пайплайны непрерывной доставки:

- **DEB:** `git-buildpackage` — управление версиями и сборка из Git-репозитория
- **RPM:** Copr (Fedora) и OBS (openSUSE) — сервисы автоматической сборки и публикации

## Полезные утилиты

| Утилита | Назначение |
| :--- | :--- |
| `debuild` | Обёртка для сборки DEB с проверками |
| `dch` / `debchange` | Редактирование changelog |
| `debconf` | Система конфигурации пакетов |
| `quilt` | Управление патчами в DEB |
| `rpmdev-bumpspec` | Автоматическое увеличение версии в spec |
| `fedpkg` / `centpkg` | Работа с Fedora/CentOS DistGit |

Дополнительные инструменты описаны в [основных понятиях сборки](./basic_concepts.md), сравнение DEB/RPM — в [обзоре управления пакетами](../linux_package_management_overview.md).

## Связанные темы

Базовые концепции: [определения](./definitions.md), [основные понятия](./basic_concepts.md), [практические сценарии](./practical_scenarios.md).

Публикация пакетов: [приватный APT-репозиторий](../deb_private_apt_repository_reprepro/practical_scenarios.md) (DEB), [управление репозиториями DNF](../dnf_commands/basic_concepts.md) (RPM).
