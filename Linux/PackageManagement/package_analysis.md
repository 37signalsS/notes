# Анализ и получение пакетов в Linux

## Определения

Ниже приведены основные термины, используемые при исследовании структуры и содержимого программного обеспечения в дистрибутивах Linux.

**Анализ пакета** — процесс изучения метаданных, содержимого, зависимостей и скриптов пакета без его обязательной установки в систему.

**Виртуальный пакет (Virtual Package)** — имя, которое не соответствует физическому пакету, но «предоставляется» другими пакетами (например, пакет `mail-transport-agent` предоставляется через `postfix` или `exim4`).

**Возможность (Capability/Provides)** — в системе RPM это именованная функция, файл или библиотека, которую пакет предоставляет другим компонентами для разрешения зависимостей.

**Метаданные пакета** — структурированная информация о пакете: версия, зависимости, краткое и полное описание, сопровождающий (maintainer), размер и целевая архитектура процессора.

**Scriptlets (Скрипты пакета)** — вспомогательные сценарии, исполняемые менеджером пакетов на различных этапах жизненного цикла (до или после установки/удаления).

**Контрольная сумма пакета** — хеш-значение (MD5, SHA1, SHA256), используемое для проверки целостности файла пакета после загрузки из репозитория.

**Цепочка поставок ПО (Software Supply Chain)** — последовательность этапов, через которые проходит программное обеспечение от разработчика до установки на целевую систему. Анализ пакетов — ключевой этап обеспечения безопасности этой цепочки.

**Подпись пакета** — GPG-подпись, подтверждающая авторство и целостность пакета. В DEB-системах проверяется через индексы репозитория и файлы `Release.gpg`. В RPM — через встроенную секцию подписи в заголовке пакета.

**SBOM (Software Bill of Materials)** — детализированный перечень компонентов ПО, их версий, зависимостей и лицензий. Форматы: CycloneDX, SPDX. В контексте package analysis используется для аудита и compliance.

---

## Основные концепции

### Структура пакетов

#### DEB (Debian Package)

Архив формата `ar` (Unix archiver), содержащий три обязательных компонента:
- `debian-binary` — текстовый файл с версией формата пакета (обычно `2.0`).
- `control.tar.*` — метаданные (файл `control`), хеш-суммы (`md5sums`) и управляющие скрипты. Может использовать сжатие `.gz`, `.xz` или `.zstd`.
- `data.tar.*` — основной архив с файлами. Современные стандарты (Debian 12+, Ubuntu 22.04+) часто используют `data.tar.zstd` для ускорения распаковки.

**Поля control-файла (Debian Control):**
- `Package` — имя пакета (должно быть уникальным).
- `Version` — версия в формате `[epoch:]upstream-version[-debian-revision]`. Эпоха (`epoch:`) используется при откате версий.
- `Architecture` — целевая архитектура (`amd64`, `all`, `any`).
- `Maintainer` — сопровождающий с email.
- `Installed-Size` — примерный размер установки в килобайтах.
- `Depends` — жесткие зависимости через запятую с версиями (например, `libc6 (>= 2.34)`).
- `Pre-Depends` — зависимости, которые должны быть удовлетворены ДО распаковки пакета (например, `dpkg`).
- `Recommends` — рекомендованные пакеты (устанавливаются по умолчанию, но могут быть отключены).
- `Suggests` — пакеты, дополняющие функциональность.
- `Breaks` — конфликты, где этот пакет сломает другой.
- `Conflicts` — пакеты, которые не могут быть установлены одновременно.
- `Provides` — виртуальные пакеты, предоставляемые этим пакетом.
- `Replaces` — файлы, которые этот пакет заменяет (позволяет перезаписывать файлы других пакетов).
- `Homepage` — URL проекта.
- `Description` — краткое и полное описание (первая строка — краткая, остальные — полное).
- `Section` — категория (например, `admin`, `net`, `libs`).
- `Priority` — `required`, `important`, `standard`, `optional`, `extra`.

#### RPM (Red Hat Package Manager)

Бинарный файл, состоящий из четырех основных секций:
- **Lead** — устаревший заголовок (32 байта) для совместимости со старыми инструментами типа `file`.
- **Подпись (Signature)** — криптографическая подпись GPG для подтверждения подлинности и целостности.
- **Заголовок (Header)** — содержит все метаданные: зависимости, версии, описания, список файлов.
- **Тело (Payload)** — архив в формате `cpio`, обычно сжатый `gzip`, `xz` или `zstd`.

**Типы зависимостей в RPM:**
- `Requires` — жесткая зависимость (аналог DEB `Depends`).
- `Recommends` — рекомендованные пакеты.
- `Suggests` — предложения.
- `Supplements` — "хорошо бы, если установлен X".
- `Enhances` — "этот пакет улучшает X".
- `Obsoletes` — пакет заменяет и делает устаревшим другой пакет при обновлении.
- `Conflicts` — пакеты, которые не могут быть установлены одновременно.
- `Provides` — виртуальные возможности (capabilities), предоставляемые пакетом.
- `Requires(pre)`, `Requires(post)` — зависимости для скриптовых этапов.

**Версия и релиз:**
- `Version` (`Epoch:Version`) — основная версия upstream.
- `Release` (`Release`) — номер пересборки дистрибутивом. Например, `1.el9` означает первую сборку для RHEL 9.

#### APK (Alpine Linux)

Сжатый `tar` архив (обычно `.apk`), содержащий файлы и метаданные в скрытом файле `.PKGINFO`. Часто используется в Docker-контейнерах из-за минимального размера.

**Поля `.PKGINFO`:**
- `pkgname`, `pkgver` — имя и версия.
- `pkgdesc` — описание.
- `url` — домашняя страница.
- `builddate` — дата сборки.
- `packager` — сборщик.
- `size` — размер в байтах.
- `arch` — архитектура.
- `origin` — исходный пакет в репозитории.
- `commit` — git-коммит источника.
- `license` — лицензия.
- `triggers` — скрипты триггеров (pre-install, post-install, etc.).
- `provides`, `replaces` — виртуальные пакеты и замены.

### Архитектурные квалификаторы зависимостей

В DEB-системах зависимости могут содержать квалификаторы архитектуры:
- `:any` — пакет может быть установлен для любой архитектуры (multiarch).
- `:native` — пакет соответствует текущей архитектуре системы.
- `:samearch` — зависимость должна быть той же архитектуры, что и пакет, который требует её.

Пример: `Depends: python3:any` позволяет установить пакет с любой архитектурой Python.

### Жизненный цикл скриптов

| Скрипт (DEB) | Скрипт (RPM) | Выполняется | Назначение |
| :--- | :--- | :--- | :--- |
| `preinst` | `%pre` | Перед установкой | Проверка системных условий, создание пользователей/групп. |
| `postinst` | `%post` | После установки | Регистрация сервисов в `systemd`, генерация сертификатов. |
| `prerm` | `%preun` | Перед удалением | Остановка активных демонов, сохранение данных. |
| `postrm` | `%postun` | После удаления | Очистка временных файлов, удаление ссылок. |

**Особенности scriptlets в RPM:**
- `%pre` и `%post` выполняются в одном транзакционном контексте. Если `%post` падает, пакет помечается как установленный, но может быть не полностью функциональным.
- `%triggerin` / `%triggerun` / `%triggerpostun` — скрипты триггеров, которые срабатывают при установке/удалении других пакетов.

---

## Практические сценарии

### Получение файлов пакетов без установки

#### APT (Debian, Ubuntu)
```bash
# Скачать файл пакета (.deb) в текущую директорию
apt-get download <package_name>

# Скачать пакет со всеми зависимостями в локальный кэш (/var/cache/apt/archives/)
apt-get install --download-only <package_name>

# Поиск пакета, которому принадлежит существующий файл в системе
dpkg -S /etc/nginx/nginx.conf
# → result: nginx-common: /etc/nginx/nginx.conf

# Поиск пакета по имени файла, если пакет не установлен (требует apt-file)
sudo apt update && sudo apt install apt-file && apt-file update
apt-file search bin/htop
```

**Валидация:**
```bash
# Проверка загруженного файла
ls -lh <package_name>*.deb
# → Размер должен быть > 0 и совпадать с размером в репозитории

# Проверка контрольной суммы
apt-get download <package_name> && md5sum <package_name>*.deb
```

#### DNF (RHEL, Fedora)
```bash
# Скачать RPM-файл в текущую директорию
dnf download <package_name>

# Скачать пакет и зависимости в указанную директорию
dnf install --downloadonly --destdir=/tmp/packages <package_name>

# Поиск пакета по файлу или возможности
dnf provides /usr/sbin/nginx
dnf provides 'python3-module(requests)'
```

**Валидация:**
```bash
# Проверка наличия загруженного RPM
ls -lh /tmp/packages/*.rpm
# → Файл присутствует, размер > 0
```

#### APK (Alpine)
```bash
# Alpine: скачать пакет без установки
apk add --download-only <package_name> # Файлы в /var/cache/apk/
```

### Глубокий анализ зависимостей

#### DEB-системы
```bash
# Почему пакет нужен в системе (APT 3.0+ / Debian 13 / Ubuntu 24.10)
apt why <package_name>

# Рекурсивный список всех зависимостей (требует apt-rdepends)
apt-rdepends <package_name>

# Визуализация графа зависимостей (требует debtree и graphviz)
debtree <package_name> | dot -Tpng > dependencies.png
```

**Валидация:**
```bash
# Проверка гравитации зависимостей
apt-rdepends <package_name> | wc -l
# → Ожидаемое количество зависимостей

# Визуальная проверка PNG
file dependencies.png
# → PNG image data
```

#### RPM-системы
```bash
# Просмотр дерева зависимостей
dnf deplist <package_name>

# Пакеты, которые зависят от данного (reverse dependencies)
dnf repoquery --whoneeds <package_name>

# Что именно предоставляет пакет (capabilities)
dnf repoquery --provides <package_name>
```

**Валидация:**
```bash
# Проверка обратных зависимостей
dnf repoquery --whoneeds <package_name> | grep -v "Warning"
# → Список пакетов без ошибок
```

### Исследование метаданных и содержимого

#### Инструментарий DEB (dpkg-deb/dpkg-query)
```bash
# Просмотр метаданных (control файл) .deb файла
dpkg-deb --info <package.deb>

# Список всех файлов внутри .deb архива
dpkg-deb --contents <package.deb>

# Метаданные установленного пакета
dpkg-query -s <package_name>

# Пользовательский формат вывода (имя и версия всех установленных пакетов)
dpkg-query -W -f='${Package} ${Version}\n'
```

**Валидация:**
```bash
# Проверка, что пакет содержит expected binary
dpkg-deb --contents <package.deb> | grep 'bin/<expected_binary>'
# → /usr/bin/<expected_binary>
```

#### Инструментарий RPM (rpm)

Утилита `rpm` работает на низком уровне: устанавливает конкретные файлы напрямую, но не умеет самостоятельно разрешать зависимости из интернета. Для этого используются высокоуровневые менеджеры (`dnf`/`yum`).

```bash
# Установка локального RPM-пакета (i — install, v — verbose, h — hash progress bar)
sudo rpm -ivh <package.rpm>

# Обновление (замена) пакета (U — upgrade)
sudo rpm -Uvh <package.rpm>
```

##### Запрос установленных пакетов и файлов

```bash
# Проверка, установлен ли пакет
rpm -q <package_name>

# Список всех установленных пакетов
rpm -qa

# Поиск пакета по абсолютному пути к файлу (ключевой инструмент аудита и forensics)
rpm -qf /usr/bin/<utility>

# Список файлов внутри установленного пакета
rpm -ql <package_name>

# Только конфигурационные файлы пакета
rpm -qc <package_name>
```

##### Инспекция RPM-файла (до установки)

```bash
# Информация из RPM-файла (p — package file, i — info)
rpm -qip <package.rpm>

# Список файлов внутри RPM-файла
rpm -qlp <package.rpm>

# Просмотр встроенных скриптов (scriptlets)
rpm -qp --scripts <package.rpm>

# Какие файлы считаются конфигурационными
rpm -qcp <package.rpm>
```

**Валидация:**
```bash
# Проверка архитектуры пакета
rpm -qip <package.rpm> | grep "Architecture"
# → Architecture: x86_64
```

#### Инструментарий APK
```bash
# Alpine: содержимое установленного пакета
apk info -L <package_name>

# Alpine: подробная информация о пакете
apk info <package_name>

# Alpine: информация из .apk файла без установки
apk info --from=<package.apk> <package_name>
```

### Анализ changelog и истории изменений

#### DEB: dpkg-query changelog
```bash
# Просмотр changelog установленного пакета
zcat /usr/share/doc/<package_name>/changelog.Debian.gz | less

# Пакеты с изменениями за последние 7 дней
for pkg in $(dpkg-query -W -f='${Package}\n'); do
  changelog="/usr/share/doc/$pkg/changelog.Debian.gz"
  if [ -f "$changelog" ]; then
    if zcat "$changelog" | grep -qE "$(date -d '7 days ago' '+%Y-%m-%d')"; then
      echo "$pkg"
    fi
  fi
done
```

#### RPM: rpm --changelog
```bash
# Просмотр changelog пакета
rpm -q --changelog <package_name> | less

# Последние 10 записей
rpm -q --changelog <package_name> | head -20
```

#### APK: apk info --changes
```bash
# Список изменений для пакета (если доступен)
apk info --changes <package_name>
```

### Верификация подписи пакета

#### DEB: apt-secure и debsig-verify
```bash
# Проверка подписи репозитория (встроено в apt update)
sudo apt update 2>&1 | grep -i "gpg\|signature"

# Проверка подписи отдельного .deb файла
debsig-verify -v <package.deb>
# → Verification succeeded

# Просмотр доступных ключей репозитория
apt-key list
```

#### RPM: rpm --checksig
```bash
# Проверка подписи RPM-файла
rpm --checksig --nopgp <package.rpm>  # без GPG
rpm --checksig <package.rpm>
# → <package.rpm>: digests signatures OK

# Проверка конкретной сигнатуры
rpm -K <package.rpm>
```

#### APK: apk verify
```bash
# Alpine: проверка подписи пакета
apk verify --with-certs <package.apk>
```

### Генерация SBOM для compliance

```bash
# DEB: SBOM через dpkg-query
dpkg-query -W -f='${Package}\t${Version}\t${Architecture}\t${Status}\n' > /tmp/sbom_deb.txt

# RPM: через dnf repoquery (предпочтительно) или rpm
dnf repoquery --installed --queryformat '%{name}-%{epoch}:%{version}-%{release}.%{arch}\n' > /tmp/sbom_rpm.txt

# Альтернатива для RPM: rpm -qa
rpm -qa --queryformat '%{name}\t%{version}-%{release}\t%{arch}\n' > /tmp/sbom_rpm.txt

# APK: через apk
apk info -vv | grep -E "^(<pkg>|<version>)" > /tmp/sbom_apk.txt

# Валидация SBOM
wc -l /tmp/sbom_*.txt
# → Количество строк соответствует количеству установленных пакетов
```

### Сравнение пакетов между версиями релизов

```bash
# DEB: сравнение списка установленных пакетов
diff <(ssh host1 "dpkg-query -W -f='${Package} ${Version}\n'") \
     <(ssh host2 "dpkg-query -W -f='${Package} ${Version}\n'") | less

# RPM: сравнение через rpm
diff <(ssh host1 "rpm -qa --queryformat='%{name} %{version}-%{release}\n'") \
     <(ssh host2 "rpm -qa --queryformat='%{name} %{version}-%{release}\n'") | less

# DNF: сравнение через dnf repoquery
diff <(ssh host1 "dnf repoquery --installed --queryformat='%{name} %{version}-%{release}.%{arch}\n'") \
     <(ssh host2 "dnf repoquery --installed --queryformat='%{name} %{version}-%{release}.%{arch}\n'") | less
```

### Восстановление файлов из поврежденного пакета

```bash
# DEB: скачать .deb и извлечь нужный файл
apt-get download <package_name>
dpkg-deb -x <package_name>*.deb /tmp/recovered/
# Копируем нужный файл обратно
cp /tmp/recovered/<path/to/file> /<path/to/file>

# RPM: скачать и извлечь
dnf download <package_name>
rpm2cpio <package_name>*.rpm | cpio -idmv
# Копируем нужный файл обратно

# Валидация
rpm -Vf /path/to/recovered/file
# → Если вывод пустой, файл восстановлен корректно
```

### Ручная распаковка (Extraction)

```bash
# DEB: извлечение файлов данных через dpkg-deb
dpkg-deb -x <package.deb> ./output_dir

# DEB: полная распаковка (извлечение всех внутренних tar-архивов)
ar x <package.deb>

# RPM: распаковка через cpio
rpm2cpio <package.rpm> | cpio -idmv

# APK: распаковка (как обычный tar)
tar -xvf <package.apk>
```

### Проверка целостности (Integrity)

#### DEB: debsums
```bash
# Проверка контрольных сумм файлов (требует debsums)
sudo debsums -s <package_name>

# Проверка всех пакетов
sudo debsums -s
# → Выводит только измененные файлы
```

#### RPM: Верификация
Команда `rpm -V <package_name>` сравнивает файлы в системе с метаданными из БД. Подробное описание кодов верификации приведено в **[Проверка целостности файлов](../Linux/Security/Concepts/file-integrity-checking.md)**.

```bash
# Полная проверка всех файлов системы
sudo rpm -Va

# Проверка конкретного пакета
sudo rpm -V <package_name>
# → Пустой вывод = файлы не изменены
```

---

## Дополнительная информация

### Выбор инструмента: Низкий уровень vs Высокий уровень

| Уровень | Инструменты | Когда использовать |
| :--- | :--- | :--- |
| **Низкий** | `dpkg`, `rpm`, `apk info` | Работа с локальными файлами, извлечение, диагностика БД. Без разрешения зависимостей. |
| **Высокий** | `apt`, `dnf`, `apk add` | Работа с репозиториями, автоматическое разрешение зависимостей, обновление системы. |

### Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `dpkg-deb: error: ...` | Файл не является .deb архивом или поврежден | Проверьте `file <package.deb>`; повторно загрузите пакет |
| `rpm: не удалось открыть <package.rpm>` | Файл поврежден или имеет неправильный формат | Проверьте `file <package.rpm>`; проверьте контрольную сумму |
| `apt-file search: нет результатов` | Кэш `apt-file` устарел | Выполните `apt-file update` и повторите поиск |
| `rpm -V показывает много 'S' и '5'` | Файлы были изменены после установки | Используйте `rpm -qf` для определения пакета, проверьте журналы изменений |
| `debtree: команда не найдена` | Утилита не установлена | `sudo apt install debtree graphviz` |
| `dnf repoquery: не удалось разрешить зависимости` | Пакет не найден в текущих репозиториях | Проверьте включенные репозитории: `dnf repolist` |

### Best Practices

1. **Анализ перед установкой:** Всегда изучайте содержимое и зависимости пакета перед установкой в production. Особенно критично для пакетов из неофициальных репозиториев.
2. **Использование SBOM:** Поддерживайте актуальный SBOM для каждой системы. Генерация через `dnf repoquery` или `dpkg-query` должна быть частью provisioning (Ansible, Puppet).
3. **Проверка подписей:** Никогда не устанавливайте пакеты без проверки GPG-подписи. В production включите `gpgcheck=1` во всех `.repo` файлах.
4. **Аудит изменений:** Регулярно сравнивайте текущий SBOM с базовой линией. Автоматизируйте через cron или systemd-timer.
5. **Изоляция анализа:** Выполняйте анализ пакетов в изолированных средах (chroot, контейнер) при работе с неизвестными пакетами.

### Безопасность

1. **Целостность:** Проверяйте контрольные суммы пакетов после загрузки. Используйте HTTPS для загрузки из репозиториев.
2. **Подписи:** Убедитесь, что ключи репозиториев актуальны и хранятся в защищенном месте (`/etc/apt/trusted.gpg.d/`, `/etc/pki/rpm-gpg/`).
3. **Минимизация поверхности:** Устанавливайте только необходимые пакеты. Каждый пакет расширяет поверхность атаки.
4. **Audit:** Мониторьте изменения в установленных пакетах через `rpm -Va` или `debsums -s` в combination с SIEM.

### Производительность

- `debtree` и визуализация могут потреблять много памяти на системах с >5000 пакетов. Используйте фильтры: `debtree <package> | grep -v '^  ' | head -50`.
- `dnf repoquery` кэширует метаданные. При анализе большого количества пакетов сначала выполните `dnf makecache`.
- `rpm -qa` на системах с >10000 пакетов может быть медленным. Используйте `rpm -qa --queryformat` с фильтрацией.

### Ограничения и известные проблемы

1. **Эпоха (epoch) в DEB:** Не отображается в `apt-cache policy` по умолчанию, но критична при сравнении версий. Используйте `apt-cache policy <package>` для просмотра.
2. **RPM Provides:** Может приводить к неожиданному разрешению зависимостей. Всегда проверяйте `dnf repoquery --provides` при отладке.
3. **Multiarch:** На системах с multiarch команды `dpkg-query` и `rpm` могут возвращать несколько архитектур. Указывайте `--arch` явно.
4. **Измененные системные файлы:** Если файлы пакета были изменены (например, через `dpkg-divert`), команды анализа могут показывать расхождения. Используйте `--status` флаги где возможно.
5. **Кеширование:** `apt-file` и `dnf` кэшируют данные. После обновления репозиториев анализ может давать устаревшие результаты. Всегда обновляйте кэш перед анализом.

### Миграция между системами

При миграции с DEB на RPM (или наоборот) используйте SBOM для перекрестной проверки покрытия пакетов. Пример генерации универсального SBOM:

```bash
# Универсальный формат (name, version, source)
{
  echo "package_name\tversion\tsource"
  dpkg-query -W -f='${Package}\t${Version}\tdeb\n'
  rpm -qa --queryformat='%{NAME}\t%{VERSION}-%{RELEASE}\trpm\n' 2>/dev/null || true
  apk info -vv | sed 's/\t/ /' | awk '{print $1 "\t" $2 "\tapk\n"}' || true
} > /tmp/unified_sbom.tsv
```

### Ресурсы для поиска пакетов онлайн

- **pkgs.org** — универсальный агрегатор пакетов.
- **Debian**: [packages.debian.org](https://packages.debian.org/)
- **Ubuntu**: [packages.ubuntu.com](https://packages.ubuntu.com/)
- **Fedora/RHEL**: [packages.fedoraproject.org](https://packages.fedoraproject.org/)
- **Alpine**: [pkgs.alpinelinux.org](https://pkgs.alpinelinux.org/packages)

### Связанные документы

- **[База данных пакетов](./package_database.md)** — структура и восстановление БД пакетов.
- **[Обзор управления пакетами](./linux_package_management_overview.md)** — сравнение систем DEB и RPM.
- **[Проверка целостности файлов](../../Security/Concepts/file-integrity-checking.md)** — детали верификации файлов и расшифровка кодов `rpm -V`.
- **[Apt Pinning](./deb_apt_pinning.md)** — управление приоритетами источников пакетов.
- **[Сборка пакетов](./package_build/basic_concepts.md)** — принципы создания пакетов, lintian и rpmlint.
- **[Команды DNF](./dnf_commands/practical_scenarios.md)** — полный справочник команд DNF.
