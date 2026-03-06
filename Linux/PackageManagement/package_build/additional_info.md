# Сборка пакетов: Дополнительная информация

## Продвинутые техники

### Чистое окружение для сборки

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

```bash
# DEB: Сборка для другой архитектуры
dpkg-buildpackage -aarm64 -us -uc

# RPM: Сборка для другой архитектуры
rpmbuild --target=aarch64 -ba SPECS/package.spec
```

### Автоматизация с CI/CD

- **DEB:** Использование `git-buildpackage` для управления версиями в Git
- **RPM:** Интеграция с Copr (Fedora) или OBS (openSUSE) для автоматической сборки

## Полезные утилиты

| Утилита | Назначение |
| :--- | :--- |
| `debuild` | Обёртка для сборки DEB с проверками |
| `dch` / `debchange` | Редактирование changelog |
| `debconf` | Система конфигурации пакетов |
| `quilt` | Управление патчами в DEB |
| `rpmdev-bumpspec` | Автоматическое увеличение версии в spec |
| `fedpkg` / `centpkg` | Работа с Fedora/CentOS DistGit |

## Сравнение систем сборки

| Аспект | DEB | RPM |
|--------|-----|-----|
| Формат пакета | `.deb` | `.rpm` |
| Файл спецификации | `debian/*` | `.spec` |
| Чистое окружение | `pbuilder`, `sbuild` | `mock` |
| Проверка качества | `lintian` | `rpmlint` |
| Управление версиями | `dch`, `git-buildpackage` | `rpmdev-bumpspec` |
| Дистрибутивы | Debian, Ubuntu | Fedora, RHEL, CentOS, openSUSE |

## Связанные темы

- **[Обзор управления пакетами](../linux_package_management_overview.md)** — базовые концепции
- **[Анализ и получение пакетов](../package_analysis.md)** — изучение метаданных и содержимого
- **[База данных пакетов](../package_database.md)** — расположение и структура баз данных
- **[Приватный APT-репозиторий](./deb_private_apt_repository_reprepro.md)** — публикация собственных DEB-пакетов
- **[Управление репозиториями DNF](./dnf_repository_management.md)** — публикация RPM-пакетов

---

## Связанные документы

- **[Определения](./definitions.md)** — базовые термины
- **[Основные понятия](./basic_concepts.md)** — этапы сборки, инструменты
- **[Практические сценарии](./practical_scenarios.md)** — сборка DEB и RPM пакетов

---

*Этот файл является частью декомпозированной документации. Исходный файл: [package_building.md](../package_building.md)*
