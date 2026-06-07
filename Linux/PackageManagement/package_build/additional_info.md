# Сборка пакетов: Дополнительная информация

## Определения

Базовые термины и глоссарий процесса сборки приведены в документе **[Определения](./definitions.md)**.

## Основные концепции

Архитектура процесса сборки, этапы и структура управляющих файлов описаны в файле **[Основные понятия](./basic_concepts.md)**.

## Практические сценарии

Пошаговые руководства по сборке пакетов для различных дистрибутивов доступны в файле **[Практические сценарии](./practical_scenarios.md)**.

---

## Дополнительная информация

### Продвинутые техники сборки

#### Изолированное окружение (Clean Build Environment)

Использование чистых сред гарантирует отсутствие "скрытых" зависимостей в системе сборки и обеспечивает воспроизводимость результата.

**DEB: pbuilder (Personal Package Builder)**

```bash
# Установка необходимых утилит
sudo apt-get install pbuilder debootstrap

# Создание базового окружения (chroot) для конкретного дистрибутива
sudo pbuilder create --distribution focal

# Сборка пакета из файла исходного пакета (.dsc)
sudo pbuilder build ../package-name_version.dsc

# Результаты сборки сохраняются в /var/cache/pbuilder/result/
```

**RPM: mock**

`mock` позволяет собирать RPM (Red Hat Package Manager) пакеты в изолированных средах `chroot`.

```bash
# Установка mock
sudo dnf install mock

# Добавление пользователя в группу mock для работы без sudo
sudo usermod -aG mock $USER

# Сборка пакета из SRPM (Source RPM) для конкретной цели (Fedora 38 x86_64)
mock -r fedora-38-x86_64 ~/rpmbuild/SRPMS/package-name.src.rpm

# Результаты сборки сохраняются в /var/lib/mock/fedora-38-x86_64/result/
```

### Кросс-компиляция

Процесс сборки пакетов для архитектуры (например, ARM64), отличной от архитектуры хоста (например, x86_64):

```bash
# DEB: Сборка для архитектуры ARM64
dpkg-buildpackage -aarm64 -us -uc

# RPM: Сборка для архитектуры AArch64
rpmbuild --target=aarch64 -ba SPECS/package.spec
```

### Автоматизация через CI/CD (Continuous Integration / Continuous Deployment)

Интеграция сборки пакетов в пайплайны непрерывной разработки:

- **DEB**: Использование `git-buildpackage` (gbp) для автоматизации сборки напрямую из Git-репозитория.
- **RPM**:
  - **Copr**: Сервис для Fedora/RHEL, аналогичный PPA (Personal Package Archive) в Ubuntu.
  - **OBS (Open Build Service)**: Мощная платформа от openSUSE для сборки пакетов под множество дистрибутивов одновременно.

---

### Полезные утилиты

| Утилита | Назначение |
| :--- | :--- |
| `debuild` | Высокоуровневая обёртка для `dpkg-buildpackage` с автоматической проверкой `lintian`. |
| `dch` / `debchange` | Быстрое редактирование файла `debian/changelog`. |
| `quilt` | Стандартный инструмент для управления патчами в DEB-системах. |
| `rpmdev-bumpspec` | Автоматическое инкрементирование версии и добавление записи в `%changelog` spec-файла. |
| `fedpkg` / `centpkg` | Специализированные инструменты для работы с инфраструктурой DistGit в Fedora и CentOS. |

### Связанные документы

- **[Основные понятия](./basic_concepts.md)** — этапы сборки и структура файлов.
- **[Практические сценарии](./practical_scenarios.md)** — пошаговые инструкции.
- **[Обзор управления пакетами](../linux_package_management_overview.md)** — сравнение систем DEB и RPM.
