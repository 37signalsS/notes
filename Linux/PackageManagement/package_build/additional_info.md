# Сборка пакетов: Дополнительная информация

## Определения

Базовые термины и глоссарий процесса сборки приведены в документе **[Определения](./definitions.md)**.

## Основные концепции

Архитектура процесса сборки, этапы и структура управляющих файлов описаны в файле **[Основные понятия](./basic_concepts.md)**.

## Практические сценарии

Пошаговые руководства по сборке пакетов для различных дистрибутивов доступны в файле **[Практические сценарии](./practical_scenarios.md)**.

---

## Продвинутые техники сборки

### Изолированное окружение (Clean Build Environment)

Использование чистых сред гарантирует отсутствие «скрытых» зависимостей в системе сборки и обеспечивает воспроизводимость результата. Для SRE это основа immutable-инфраструктуры: каждый пакет собирается в одинаковой, контролируемой среде, что исключает «works on my machine».

**DEB: sbuild и pbuilder**

`sbuild` является современным стандартом для сборки пакетов в Debian/Ubuntu. `pbuilder` и его инкрементальный аналог `cowbuilder` используют COW (Copy-On-Write) для ускорения повторных сборок за счет переиспользования базового chroot.

```bash
# Установка sbuild и cowbuilder
sudo apt-get install sbuild debootstrap devscripts cowbuilder

# Создание базового окружения (chroot) для конкретного релиза
sudo sbuild-createchroot bookworm /srv/chroot/bookworm-amd64-sbuild http://deb.debian.org/debian

# Сборка пакета из .dsc файла
sbuild -d bookworm --no-clean package-name_version.dsc

# cowbuilder: инкрементальная сборка (быстрее повторных запусков)
sudo cowbuilder --build package-name_version.dsc --basepath /var/cache/pbuilder/base-bookworm.cow
```

**Важно для SRE:** флаг `--no-clean` сохраняет chroot для отладки, но требует ручной очистки (`sbuild --clean`) для предотвращения накопления мусора и утечек дискового пространства.

**RPM: mock**

`mock` позволяет собирать RPM-пакеты в изолированных chroot-средах, используя конфигурации из `/etc/mock/`.

```bash
# Сборка пакета для конкретной цели с использованием внешних репозиториев
mock -r rockylinux-9-x86_64 --rebuild ~/rpmbuild/SRPMS/package-name.src.rpm

# Очистка окружения после сборки
mock -r rockylinux-9-x86_64 --clean

# Монтирование каталога с исходниками для отладки
mock -r rockylinux-9-x86_64 --shell --no-clean
```

**Типичные ошибки и решения:**

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `mock: command not found` | В chroot не установлен базовый набор инструментов | Убедитесь, что в конфигурации mock указан репозиторий с `@buildsys-build` |
| `sbuild: debootstrap failed` | Сетевой доступ к репозиторию заблокирован | Проверьте DNS и firewall в среде сборки |
| `quilt push: patch does not apply` | Апстрим-версия изменилась, патч устарел | Пересоздайте патч через `quilt refresh --refresh` или откатите его |
| `No space left on device` | Chroot заполнен кэшем или артефактами | Выполните `mock --clean` или очистите `/var/cache/mock/` |

### Кросс-архитектурная сборка

Сборка пакетов для архитектур, отличных от хостовой (например, сборка ARM64 на x86_64), требует эмуляции через `QEMU` и регистрации `binfmt_misc`.

```bash
# Установка эмулятора и регистрация binfmt_misc
sudo apt-get install qemu-user-static binfmt-support

# Проверка регистрации
file /usr/bin/qemu-aarch64-static
# → /usr/bin/qemu-aarch64-static: ELF 64-bit LSB executable, ARM aarch64

# В sbuild это настраивается через указание архитектуры
sbuild -d bookworm --arch=arm64 package-name_version.dsc
```

**Для SRE важно:** кросс-архитектурная сборка значительно медленнее нативной из-за эмуляции. Для production-пайплайнов предпочтительнее использование native-сборочных нод (ARM64 runners) или ферм ( `mock` на ARM64 хосте ).

### Воспроизводимые сборки (Reproducible Builds)

Обеспечивают получение побитово идентичных бинарных файлов из тех же исходников. Это критично для безопасности цепочки поставок (Supply Chain Security) и compliance.

*   **SOURCE_DATE_EPOCH**: Основная переменная окружения, используемая для фиксации временных меток в создаваемых архивах и заголовках.
*   **Анализ различий (diffoscope)**: Инструмент для глубокого сравнения архивов и бинарных файлов. Помогает выявить причины расхождений (пути к директориям, порядок файлов, метаданные).
    ```bash
    diffoscope original.deb rebuild.deb
    ```
*   **strip-nondeterminism**: Удаляет недетерминированные данные (timestamps, встроенные пути) из уже собранных артефактов.
    ```bash
    strip-nondeterminism --keep-time package.deb
    ```
*   **reprotest**: Автоматизированный запуск повторных сборок и сравнение результатов.
    ```bash
    reprotest --build-environment apt-get --diffoscope package-name_version.dsc
    ```

**Практический совет:** интеграция `reprotest` в CI как gate-стадия гарантирует, что каждое изменение в пайплайне не нарушает воспроизводимость.

---

## Автоматизация через CI/CD

### Подпись пакетов в пайплайнах

Для обеспечения безопасности в CI/CD (GitHub Actions, GitLab CI) GPG-ключи должны храниться в зашифрованных секретах переменных окружения.

```bash
# Пример подписи RPM в CI (rpmsign)
echo "$GPG_PRIVATE_KEY" | gpg --import
rpmsign --addsign package.rpm

# Проверка подписи
rpm -K package.rpm
```

**GitHub Actions пример:**
```yaml
name: Build and Sign RPM
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Import GPG key
        run: echo "${{ secrets.GPG_PRIVATE_KEY }}" | gpg --import
      - name: Build package
        run: |
          rpmdev-setuptree
          dnf builddep -y *.spec
          rpmbuild -ba *.spec
      - name: Sign package
        run: rpmsign --addsign ~/rpmbuild/RPMS/*/*.rpm
      - name: Upload artifacts
        uses: actions/upload-artifact@v4
        with:
          name: rpms
          path: ~/rpmbuild/RPMS/*/*.rpm
```

**Для DEB:**
```bash
# Подпись changes-файла
debsign --re-sign -k$GPG_KEY_ID package_1.0-1_amd64.changes

# Или подпись отдельных файлов
debsig-verify -v package.deb
```

**Enterprise-практики:**
- **HSM / Yubikey:** хранение мастер-ключей вне CI-серверов. Подпись происходит через `gpg --pinentry-program` с физическим токеном.
- **Ротация ключей:** регулярная смена GPG-ключей (раз в 6-12 месяцев) с сохранением старых ключей для верификации исторических артефактов.
- **Политика подписи:** все пакеты, попадающие в production-репозиторий, должны иметь валидную подпись. Отсутствие подписи = automatic rejection в пайплайне.

### Внешние сервисы сборки

1.  **OBS (Open Build Service)**: Универсальная платформа от openSUSE. Поддерживает сборку под Debian, Ubuntu, RHEL, Fedora, SUSE из одного исходного кода.
2.  **Copr (Cool Other Package Repo)**: Сервис для экосистемы Red Hat. Позволяет создавать персональные репозитории.
3.  **Launchpad PPA**: Основной сервис для Ubuntu.

**Для SRE:** внешние сервисы удобны для open-source проектов, но в корпоративной среде предпочтительнее self-hosted решения (own OBS instance, internal Nexus/Artifactory) для соблюдения data residency и audit requirements.

---

## Анализ и инспекция артефактов

После сборки пакет должен пройти статический анализ на соответствие политикам дистрибутива.

| Инструмент | Назначение |
| :--- | :--- |
| **lintian** | Статический анализатор DEB-пакетов (Debian Policy). |
| **rpmlint** | Анализатор RPM-пакетов (Fedora Packaging Guidelines). |
| **diffoscope** | Глубокий бинарный diff артефактов. |
| **check-all-the-things** | Агрегатор тестов безопасности для исходного кода. |
| **strip-nondeterminism** | Удаление недетерминированных данных (timestamps, пути). |

**Практика CI-gate:**
```bash
# DEB: fail on any E: error
lintian --fail-on-error --tag-display-limit 0 ../package_1.0-1_amd64.deb

# RPM: fail on any error
rpmlint -f /etc/rpmlint/config ~/rpmbuild/RPMS/x86_64/package-1.0-1.el9.x86_64.rpm
```

---

## Локальное обслуживание пакетных репозиториев

После сборки пакеты необходимо разместить в репозитории для распространения. В air-gapped или корпоративных средах это критически важно.

**DEB: reprepro**

```bash
# Установка
sudo apt-get install reprepro

# Инициализация репозитория
mkdir -p /srv/repo/{conf,incoming,pool,dists}
cat > /srv/repo/conf/distributions <<EOF
Origin: CompanyInternal
Label: Company Internal Packages
Codename: bookworm-internal
Architectures: amd64 arm64
Components: main
Description: Internal package repository
SignWith: 12345678
EOF

# Добавление пакета
reprepro -b /srv/repo includedeb bookworm-internal package_1.0-1_amd64.deb
```

**RPM: createrepo**

```bash
# Установка
sudo dnf install createrepo_c rpm-sign

# Создание репозитория
mkdir -p /srv/repo/rpm/9/x86_64
cp package-1.0-1.el9.x86_64.rpm /srv/repo/rpm/9/x86_64/

# Генерация метаданных
createrepo_c /srv/repo/rpm/9/x86_64

# Подпись репозитория (опционально, для дополнительной безопасности)
gpg --detach-sign --armor /srv/repo/rpm/9/x86_64/repodata/repomd.xml
```

**Для SRE:**
- Репозиторий должен размещаться на Nginx/Apache с TLS или на fileshare с HTTPS.
- Подпись метаданных репозитория (`repomd.xml`) предотвращает MITM-атаки при установке пакетов.
- В air-gapped средах используйте `reposync` для зеркалирования upstream-репозиториев.

---

## Стратегии бэкпортирования (Backporting)

Процесс переноса новой версии ПО в более старый релиз дистрибутива.

**DEB:**
1.  **Получение исходников:** `apt-get source package-name` из целевого дистрибутива (stable).
2.  **Обновление версии:** `dch -i "Backported to bookworm"` → создает запись в `debian/changelog` с суффиксом `~bookworm1`.
3.  **Адаптация патчей:** Проверка совместимости патчей со старой базой кода. Удаление или переписывание несовместимых.
4.  **Сборка и тестирование:** `sbuild -d bookworm` + запуск тестового сценария.
5.  **Загрузка в репозиторий:** `reprepro includedeb bookworm-backports package_1.0-1~bookworm1_amd64.deb`.

**RPM:**
1.  **Обновление релиз-тега:** `rpmdev-bumpspec -c "Backport to EL9" *.spec` → изменяет `Release: 1%{?dist}` на `Release: 1.el9_backport`.
2.  **Адаптация:** Проверка `BuildRequires` на наличие в целевом релизе. При необходимости добавление `%if 0%{?rhel} == 9` условий.
3.  **Сборка:** `mock -r rockylinux-9-x86_64 --rebuild package.src.rpm`.

**Учет приоритетов (Pinning) для бэкпортов:**
На стороне клиента backports имеют низкий приоритет по умолчанию. Для безопасного использования отдельных пакетов из backports без обновления всей системы используйте Apt Pinning. Подробнее в документе **[Apt Pinning](../deb_apt_pinning.md)**.

---

## Управление версионированием и релизами

Согласованное версионирование пакетов необходимо для корректного обновления и отката в production.

**DEB (semantic versioning with revision):**
```
package_1.2.3-1~internal1_amd64.deb
├── 1.2.3       ← upstream version
├── -1          ← debian revision
└── ~internal1  ← internal patch level (pre-release, lower priority)
```

**RPM:**
```
package-1.2.3-1.el9.internal1.x86_64.rpm
├── 1.2.3       ← upstream version
├── 1           ← release
├── el9         ← distribution tag
└── internal1   ← internal release
```

**Правила для SRE:**
- **Epoch (DEB):** используйте только при переименовании пакета или абсолютной необходимости сброса версии. Epoch (`0:1.0-1`) переопределяет обычное сравнение версий.
- **Release tag (RPM):** инкрементируйте при каждом изменении в spec-файле без обновления upstream-версии.
- **Changelog:** каждый релиз должен содержать описание изменений, совпадающее с commit-сообщениями в git.

---

## Откат, очистка и обслуживание артефактов

### Очистка сборочных сред

```bash
# DEB: очистка sbuild
sbuild --clean --purge

# RPM: очистка mock
mock -r rockylinux-9-x86_64 --clean

# Удаление устаревших chroot
sudo rm -rf /srv/chroot/bookworm-*
```

### Управление кэшем

```bash
# Очистка кэша apt (сборочные ноды)
sudo apt-get clean
sudo rm -rf /var/cache/apt/archives/*.deb

# Очистка кэша mock
sudo rm -rf /var/cache/mock/*

# ccache статистика и очистка
ccache -s
ccache -C
```

### Откат пакетов

В случае проблем с production-развертыванием:
1. **Зафиксируйте текущую версию:** `apt-mark hold package` или `dnf versionlock add package`.
2. **Установите предыдущую версию:** `apt-get install package=1.0.0-1` или `dnf downgrade package-1.0.0-1`.
3. **Удалите проблемный пакет:** `apt-get remove package` или `dnf remove package`.
4. **Проверьте зависимости:** `apt-get autoremove` / `dnf autoremove` для удаления неиспользуемых зависимостей.

---

## Связанные документы

- **[Основные понятия](./basic_concepts.md)** — этапы сборки и архитектура.
- **[Безопасность цепочки поставок](../../../Security/Supply_Chain_Security/overview.md)** — роль воспроизводимых сборок и SBOM.
- **[Apt Pinning](../deb_apt_pinning.md)** — управление приоритетами пакетов.
