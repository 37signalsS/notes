# Маппинг авторов в Git (.mailmap)

## Определения

**`.mailmap`** — текстовый файл, используемый для сопоставления (маппинга) различных имен и email-адресов авторов с их единой, канонической идентичностью в истории репозитория. Файл обычно версионируется (хранится в корне репозитория), что позволяет всей команде видеть унифицированную историю.

**Каноническая идентичность** — эталонное сочетание имени и email автора, которое Git должен использовать при выводе статистики и истории, даже если в метаданных коммитов указаны другие данные.

---

## Базовые концепции

### Назначение

Механизм `mailmap` решает проблему "раздвоения" личностей в истории проекта, которая возникает из-за:
* Использования разных email-адресов (личный, рабочий, корпоративный).
* Опечаток в имени или email при настройке `git config`.
* Смены фамилии или предпочтительного написания имени.
* Изменения политики корпоративных адресов.
* Объединения нескольких независимых репозиториев в один (monorepo).

### Форматы записей

В файле `.mailmap` поддерживается четыре типа записей. Порядок аргументов: **СНАЧАЛА канонические данные, ЗАТЕМ заменяемые**.

| Формат | Описание |
| :--- | :--- |
| `Имя <kanon@mail.ru> <old@mail.ru>` | Заменяет все вхождения `old@mail.ru` на `Имя <kanon@mail.ru>` |
| `Имя <kanon@mail.ru> <kanon@mail.ru>` | Исправляет только имя для конкретного email |
| `Имя <kanon@mail.ru> Старое <old@mail.ru>` | Заменяет конкретную пару имя+email на новую пару |
| `Имя <kanon@mail.ru> Старое` | Исправляет имя и email, если имя совпадает со "Старое" |

**Особенности синтаксиса:**
* **Комментарии:** Строки, начинающиеся с `#`, игнорируются.
* **Регистр:** Сравнение имен и email-адресов происходит **регистронезависимо** (case-insensitive).
* **Порядок:** Если для одного и того же старого адреса указано несколько правил, Git использует **первое найденное** в файле.

### Плейсхолдеры для вывода

При использовании `git log --format` важно различать плейсхолдеры, которые учитывают маппинг, и те, что выводят "сырые" данные:

| Тип | Сырые данные | С учетом Mailmap |
| :--- | :--- | :--- |
| **Имя автора** | `%an` | `%aN` |
| **Email автора** | `%ae` | `%aE` |
| **Имя коммиттера** | `%cn` | `%cN` |
| **Email коммиттера** | `%ce` | `%cE` |

### Приоритет и расположение

Git ищет правила в следующем порядке (первое найденное правило выигрывает):
1.  **Локальный конфиг:** Файл, указанный в `git config mailmap.file`.
2.  **Корень репозитория:** Файл `.mailmap` в рабочей директории.
3.  **Глобальный конфиг:** Файл, указанный в `git config --global mailmap.file`.
4.  **Git-объект (Blob):** Объект, указанный в `mailmap.blob`. Это позволяет хранить правила в отдельной ветке или ссылаться на конкретный коммит:
    ```bash
    git config mailmap.blob "HEAD:.mailmap"
    ```

### Особенности инструментов

* **Локальные инструменты:** `git log`, `git shortlog`, `git blame` и `git check-mailmap` по умолчанию учитывают `.mailmap`.
* **GitHub:** Поддержка частичная.
    * **Комиты:** Веб-интерфейс обычно отображает оригинальные данные коммита.
    * **График вклада:** Может использовать `.mailmap` для консолидации (обновление занимает до 24ч), но самый надежный способ — добавить все email в настройки профиля GitHub.
* **GitLab:** Уважает `.mailmap` в статистике проекта, но для корректного связывания коммитов с профилем пользователя email должны быть подтверждены в аккаунте.

### Предварительные требования

* **Версия Git:** Рекомендуется Git 2.30+ для полной поддержки всех функций mailmap.
* **Базовые знания:** Понимание структуры коммитов в Git (автор vs коммиттер, метаданные). Подробнее — в [Основы Git](./git_basics.md).
* **Настройка Git:** Должны быть настроены `user.name` и `user.email`. Подробнее — в [Конфигурация Git](./git_configuration.md).

---

## Практические сценарии

### Сценарий 1: Объединение истории после смены email

Разработчик использовал личный почтовый ящик до перехода на корпоративный:

```text
# .mailmap
Ivan Petrov <ivan@corp.com> <ivan.p@gmail.com>
Ivan Petrov <ivan@corp.com> <ivan@old-job.com>
```

**Валидация:**
```bash
# Проверить, что старые email маппятся на новый
git check-mailmap "Ivan Petrov <ivan.p@gmail.com>"
# → Ivan Petrov <ivan@corp.com>

git check-mailmap "Ivan Petrov <ivan@old-job.com>"
# → Ivan Petrov <ivan@corp.com>

# Проверить статистику (дубли должны объединиться)
git shortlog -sne --all | grep "Ivan"
# → 215  Ivan Petrov <ivan@corp.com>
```

**Edge cases:**
* Если разработчик коммитил без настроенного email (через дефолтный), маппинг может не сработать — проверьте "сырые" данные через `git log --format="%an <%ae>"`.
* Email в коммите должен точно совпадать (включая регистр домена — сравнение case-insensitive).

### Сценарий 2: Исправление опечаток в именах

```text
# .mailmap
Alexander Ivanov <alex@corp.com> Alex Ivanov <alex@corp.com>
Alexander Ivanov <alex@corp.com> A. Ivanov <alex@corp.com>
```

**Валидация:**
```bash
# Проверить различные варианты написания
git check-mailmap "Alex Ivanov <alex@corp.com>"
# → Alexander Ivanov <alex@corp.com>

git check-mailmap "A. Ivanov <alex@corp.com>"
# → Alexander Ivanov <alex@corp.com>

# Убедиться, что статистика объединилась
git shortlog -sne | grep -i "alexander\|alex\|a."
# → 142  Alexander Ivanov <alex@corp.com>
```

**Edge cases:**
* Если имя содержит спецсимволы (дефисы, апострофы), убедитесь в точном совпадении строк.
* Маппинг работает только для отображения — метаданные коммита не изменяются.

### Сценарий 3: Проверка правил через `check-mailmap`

Инструмент позволяет проверить, как Git преобразует конкретную строку автора (доступно с Git 1.8.4):

```bash
# Проверка строки
git check-mailmap "Alex Ivanov <alex@corp.com>"
# → Alexander Ivanov <alex@corp.com>

# Проверка через файл (указать свой .mailmap)
git check-mailmap --mailmap-file=custom-mailmap.txt "Old Name <old@mail.com>"
# → New Name <new@mail.com>

# Проверка нескольких строк из файла
cat authors.txt | git check-mailmap --stdin
# → Proper Name <proper@email.com>
# → Another Name <another@email.com>
```

**Валидация:**
```bash
# Если правило не найдено — возвращается исходная строка
git check-mailmap "Unknown <unknown@mail.com>"
# → Unknown <unknown@mail.com>
```

**Edge cases:**
* `check-mailmap` использует все источники маппинга (локальный `.mailmap`, глобальный, `mailmap.file`).
* Для проверки конкретного файла используйте `--mailmap-file`.

### Сценарий 4: Глобальная настройка для всех проектов

Если вы хотите видеть свои старые коммиты под новым именем во всех локальных репозиториях:

```bash
# Создать глобальный файл
echo "My Name <me@current.com> <me@old.com>" >> ~/.git-mailmap
echo "My Name <me@current.com> <me@old-job.com>" >> ~/.git-mailmap

# Настроить Git
git config --global mailmap.file ~/.git-mailmap
```

**Валидация:**
```bash
# Проверить настройку
git config --global mailmap.file
# → /Users/username/.git-mailmap

# Проверить маппинг в любом репозитории
cd /some/repo
git check-mailmap "My Name <me@old.com>"
# → My Name <me@current.com>
```

**Edge cases:**
* Глобальный mailmap применяется ко всем репозиториям на машине — используйте для личных данных.
* Локальный `.mailmap` в репозитории имеет приоритет над глобальным (если настроен через `mailmap.file`).

### Сценарий 5: Анализ истории с использованием mailmap

```bash
# Посмотреть топ контрибьюторов с учетом объединения дублей (-e выводит email)
git shortlog -sne --all
# → 150  Ivan Petrov <ivan@corp.com>
# →  80  Maria Sidorova <maria@corp.com>

# Вывод лога с каноническими данными
git log --format="%aN <%aE> — %s"
# → Ivan Petrov <ivan@corp.com> — feat: add new feature
# → Maria Sidorova <maria@corp.com> — fix: resolve bug

# Сравнение: сырые данные vs маппинг
git log --format="%an <%ae> → %aN <%aE>"
# → ivan.p@gmail.com <ivan.p@gmail.com> → Ivan Petrov <ivan@corp.com>

# Подсчет коммитов конкретного автора (с учетом маппинга)
git log --author="Ivan Petrov" --oneline | wc -l
# → 150
```

**Валидация:**
```bash
# Убедиться, что mailmap работает в логе
git log --format="%aN" | sort -u | grep "Ivan"
# → Ivan Petrov
# (только каноническое имя, без дублей)
```

**Edge cases:**
* `git shortlog` по умолчанию использует mailmap.
* `git log --author` ищет по каноническому имени после маппинга.
* Флаг `--no-mailmap` отключает маппинг для любой команды.

### Сценарий 6: Генерация заготовки .mailmap

Для поиска всех уникальных комбинаций имен и email в истории:

```bash
# Сгенерировать шаблон всех авторов
git log --format="%aN <%aE>" | sort -u > .mailmap.template
# → ivan.p@gmail.com <ivan.p@gmail.com>
# → Ivan Petrov <ivan@corp.com>
# → ivan@old-job.com <ivan@old-job.com>

# Или с использованием mailmap (только уникальные канонические имена)
git log --format="%aN <%aE>" | sort -u
# → Ivan Petrov <ivan@corp.com>
# → Maria Sidorova <maria@corp.com>

# Найти дубли email с разными именами (потенциальные проблемы)
git log --format="%ae %aN" | sort -u | awk '{print $1}' | sort | uniq -d
# → alex@corp.com (используется с разными именами)
```

**Валидация:**
```bash
# Проверить содержимое шаблона
cat .mailmap.template
# → (список уникальных авторов)

# После редактирования .mailmap проверить результат
git shortlog -sne
# → (статистика без дублей)
```

**Edge cases:**
* Шаблон требует ручного редактирования — добавьте канонические имена слева.
* Для больших репозиториев генерация может занять время — используйте `--since` для ограничения.

### Сценарий 7: Работа в Bare-репозиториях или CI/CD

В окружениях, где рабочая копия отсутствует (например, на сервере автоматизации), можно использовать `mailmap.blob`, чтобы Git брал правила напрямую из базы объектов:

```bash
# Настройка использования файла из ветки master
git config mailmap.blob "master:.mailmap"

# Или из конкретного коммита
git config mailmap.blob "abc1234:.mailmap"

# Проверка
git check-mailmap "Old Name <old@mail.com>"
# → New Name <new@mail.com>
```

**Валидация:**
```bash
# Проверить текущую настройку
git config mailmap.blob
# → master:.mailmap

# Проверить, что blob существует
git cat-file -e master:.mailmap && echo "OK"
# → OK
```

**Edge cases:**
* `mailmap.blob` требует, чтобы файл был закоммичен в указанной ветке/коммите.
* Полезно в CI/CD, где рабочая копия может быть минимальной (shallow clone).

### Сценарий 8: Настройка для патчей (git send-email)

Если вы отправляете патчи через email, можно настроить маппинг специально для этого инструмента (Git 2.40+):

```bash
# Использовать отдельный файл для маппинга при отправке писем
git config sendemail.mailmap.file ~/.git-send-email-map

# Или отключить маппинг для send-email
git config sendemail.mailmap false
```

**Валидация:**
```bash
# Проверить настройку
git config sendemail.mailmap.file
# → /Users/username/.git-send-email-map

# Проверить send-email без отправки (dry-run)
git send-email --dry-run --to=test@example.com HEAD~1
# → (вывод с каноническим именем автора)
```

**Edge cases:**
* `sendemail.mailmap` независим от обычного `mailmap.file`.
* Отключение (`false`) полезно, если патчи должны содержать оригинальные данные автора.

### Сценарий 9: Массовый импорт истории из другого репозитория

При объединении репозиториев в monorepo разработчики могут иметь разные идентичности:

```bash
# 1. Импортировать историю (например, через git fetch + merge)
git fetch ../old-repo.git main:old-main
git merge old-main --allow-unrelated-histories
# → Merge made by the 'ort' strategy.

# 2. Сгенерировать .mailmap из объединенной истории
git log --format="%aN <%aE>" | sort -u > .mailmap.template

# 3. Отредактировать .mailmap для объединения дублей
cat >> .mailmap << 'EOF'
Ivan Petrov <ivan@corp.com> Ivan P. <ivan@old-repo.com>
Ivan Petrov <ivan@corp.com> ivan.petrov@personal.com
EOF

# 4. Проверить результат
git shortlog -sne | head -20
# → 500  Ivan Petrov <ivan@corp.com>
# → 300  Maria Sidorova <maria@corp.com>
```

**Валидация:**
```bash
# Проверить, что история объединилась корректно
git log --format="%aN <%aE>" | sort | uniq -c | sort -rn | head
# → 500 Ivan Petrov <ivan@corp.com>
# → 300 Maria Sidorova <maria@corp.com>
# → (без дублей)
```

**Edge cases:**
* При импорте через `git filter-branch` или `git filter-repo` метаданные авторов сохраняются.
* Для SVN→Git миграции используйте `git svn clone --authors-file=authors.txt`.

### Сценарий 10: Интеграция с IDE и инструментами анализа

Настройка mailmap для корректного отображения в IDE и инструментах:

```bash
# Проверить, что mailmap работает в git blame
git blame README.md | head -5
# → abc1234 (Ivan Petrov 2026-08-20) line content

# Отключить mailmap для blame (если нужны оригинальные данные)
git blame --no-mailmap README.md | head -5
# → abc1234 (ivan.p@gmail.com 2026-08-20) line content

# Проверка через git log с графикой
git log --graph --format="%h %aN <%aE>" --all | head -20
# → * abc1234 Ivan Petrov <ivan@corp.com>
# → * def5678 Maria Sidorova <maria@corp.com>
```

**Валидация:**
```bash
# Убедиться, что IDE (VS Code, IntelliJ) использует mailmap
# Настройки IDE: Git → Enable mailmap (включено по умолчанию)
```

**Edge cases:**
* Некоторые IDE требуют перезапуска для применения изменений `.mailmap`.
* `git blame --no-mailmap` полезен для отладки маппинга.

---

## Troubleshooting

### Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| Mailmap не работает | Файл не в корне репозитория или опечатка в имени. | Убедитесь, что `.mailmap` в корне и закоммичен. |
| Дубли не объединяются | Неправильный порядок аргументов (каноническое имя должно быть первым). | Проверьте синтаксис: `Каноническое <email> Старое <email>`. |
| GitHub не показывает объединение | Обновление занимает до 24ч или email не добавлен в профиль. | Добавьте все email в настройки GitHub. |
| `check-mailmap` возвращает исходную строку | Правило не найдено или не совпадает email. | Проверьте регистр и точное совпадение email. |
| Mailmap не применяется в CI | Используется shallow clone или bare-репозиторий. | Настройте `mailmap.blob` для CI. |

### Диагностика

```bash
# Проверить, какой mailmap используется
git config --show-origin mailmap.file
# → file:.git/config  (локальная настройка)
# → file:/Users/username/.gitconfig  (глобальная настройка)

# Проверить mailmap.blob
git config mailmap.blob
# → master:.mailmap

# Отладка: проверить конкретную строку
git check-mailmap "Test User <test@example.com>"
# → (вывод с маппингом или исходная строка)

# Проверить, что .mailmap закоммичен
git ls-files .mailmap
# → .mailmap

# Отключить mailmap для диагностики
git --no-mailmap log --format="%an <%ae>" | sort -u
# → (сырые данные без маппинга)
```

---

## Best Practices

1.  **Создайте `.mailmap` в начале проекта** — это предотвратит накопление дублей в будущем.
2.  **Документируйте маппинг** — добавьте комментарий в начале `.mailmap` с описанием структуры.
3.  **Используйте `check-mailmap` для проверки** — всегда валидируйте правила после добавления.
4.  **Закоммитьте `.mailmap`** — это обеспечит единое отображение истории у всей команды.
5.  **Добавьте все email в профиль GitHub/GitLab** — это дополнительный уровень консолидации.
6.  **Обновляйте mailmap при смене email** — не забывайте добавлять новые правила при смене работы.
7.  **Используйте глобальный mailmap для личных данных** — чтобы не дублировать правила в каждом проекте.
8.  **Проверяйте статистику после изменений** — `git shortlog -sne` покажет результат маппинга.

---

## Дополнительная информация

### Официальные ресурсы

* **[Документация Git: gitmailmap](https://git-scm.com/docs/gitmailmap):** Спецификация формата и примеры.
* **[Git Check-mailmap](https://git-scm.com/docs/git-check-mailmap):** Описание команды для тестирования правил.

### Связанные темы

* [Обзор специальных файлов Git](./git_special_files_overview.md) — классификация и роль .mailmap в проекте.
* [Git Shortlog](./git_shortlog.md) — отчёты по авторам, где .mailmap применяется для канонизации имён.
* [Конфигурация Git](./git_configuration.md) — mailmap.file, mailmap.blob настройки.
* [Манипуляции с историей Git](./git_history_manipulation.md) — mailmap и переименование авторов при фильтрации.
* [Основы Git](./git_basics.md) — структура коммитов и метаданные.
