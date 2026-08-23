# Git Archive и Git Bundle — экспорт и офлайн-передача

## Определения

**git archive** — команда для создания архива (zip, tar, tar.gz) содержимого конкретного коммита или ветки без `.git` директории.

**git bundle** — команда для упаковки репозитория (или его части) в один файл `.bundle`, содержащий объекты Git и ссылки. Позволяет передавать репозиторий офлайн.

**export-ignore** — атрибут `.gitattributes`, исключающий файлы из архива `git archive`.

**export-subst** — атрибут `.gitattributes`, подставляющий переменные Git (`$Format:...$`) в файлы при архивации.

---

## Базовые концепции

### archive vs bundle vs clone

| Критерий | git archive | git bundle | git clone |
| :--- | :--- | :--- | :--- |
| Содержит `.git` | Нет | Да (упакованный) | Да |
| История коммитов | Нет | Да (опционально) | Да |
| Дельты/объекты | Нет | Да | Да |
| Remote-ссылки | Нет | Нет | Да |
| Использование | Release архивы | Офлайн-передача | Копирование репо |
| Формат | .zip, .tar, .tar.gz | .bundle | Полный репо |

### Формат bundle

```text
# v2 git bundle
<SHA-1> HEAD
<SHA-1> refs/heads/main
<SHA-1> refs/heads/feature

[объекты Git]
```

---

## Практические сценарии

### Сценарий 1: Создание архива для релиза

```bash
# Архив текущей ветки (HEAD)
git archive -o release.zip HEAD

# Архив конкретного тега
git archive -o v1.0.0.tar.gz v1.0.0

# Архив с префиксом внутри архива
git archive --prefix=myapp-1.0/ -o release.zip v1.0.0

# Архив конкретного каталога
git archive --prefix=src/ -o source.zip HEAD -- src/
```

**Валидация:**
```bash
# Проверить содержимое архива
unzip -l release.zip
# → ... (файлы без .git)
```

### Сценарий 2: Исключение файлов из архива

```bash
# Создать/отредактировать .gitattributes
echo "tests/ export-ignore" >> .gitattributes
echo ".gitignore export-ignore" >> .gitattributes
echo "*.md export-ignore" >> .gitattributes

# Теперь архив НЕ будет содержать эти файлы
git archive -o release.zip HEAD
```

**Валидация:**
```bash
unzip -l release.zip | grep "tests/"
# → (пусто — файлы исключены)
```

### Сценарий 3: Подстановка переменных в архиве

```bash
# В файле VERSION.txt:
# $Format:%(describe:tags=true)$

# При архивации переменная заменяется
git archive -o release.zip HEAD
# → Внутри VERSION.txt будет: v1.0.0-5-gabc1234
```

**Форматы подстановки:**
| Переменная | Результат |
| :--- | :--- |
| `%H` | Полный SHA-1 коммита |
| `%h` | Короткий SHA-1 |
| `%D` | Описание (describe) |
| `%t` | Тег (describe, tags=true) |
| `%ci` | Дата коммита (ISO) |

### Сценарий 4: Создание bundle для офлайн-передачи

```bash
# Упаковать весь репозиторий
git bundle create repo.bundle --all

# Упаковать конкретную ветку
git bundle create feature.bundle main

# Упаковать последние 10 коммитов ветки
git bundle create recent.bundle main~10..main

# Упаковать с тегами
git bundle create release.bundle --all --tags
```

**Валидация:**
```bash
# Проверить bundle
git bundle verify repo.bundle
# → repo.bundle is okay

# Посмотреть содержимое
git bundle list-heads repo.bundle
# → abc1234 refs/heads/main
# → def5678 refs/heads/feature
```

### Сценарий 5: Восстановление из bundle

```bash
# Клонировать из bundle
git clone repo.bundle restored-repo

# Или добавить как remote
cd existing-repo
git remote add bundle /path/to/repo.bundle
git fetch bundle
git merge bundle/main
```

### Сценарий 6: Инкрементальный bundle

```bash
# Первый bundle — полный
git bundle create full.bundle main

# Второй bundle — только дельта
git bundle create incremental.bundle main~5..main

# Проверить, что incremental зависит от full
git bundle verify incremental.bundle
# → incremental.bundle requires prerequisite: full.bundle
```

### Сценарий 7: Использование в CI/CD

```yaml
# GitHub Actions: создание архива
- name: Create release archive
  run: |
    git archive --prefix=myapp-${{ github.ref_name }}/ \
      -o myapp-${{ github.ref_name }}.zip HEAD

- name: Upload release
  uses: actions/upload-artifact@v4
  with:
    name: myapp-${{ github.ref_name }}
    path: myapp-${{ github.ref_name }}.zip
```

---

## Особенности и ограничения

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `fatal: not a tree object` | Некорректный ref | Указать существующий тег или ветку |
| `fatal: not a valid bundle file` | Повреждённый bundle | Пересоздать bundle |
| `Repository lacks these prerequisite commits` | Инкрементальный bundle без base | Добавить base bundle через `git fetch` |
| Файлы не исключаются из архива | `.gitattributes` не закоммичен | Сделать `git add .gitattributes && git commit` |

### Best Practices

1. **Используйте `--prefix`** для архивов — чтобы файлы были в подпапке.
2. **Настройте `export-ignore`** в `.gitattributes` для исключения тестов/документации.
3. **Используйте bundle для офлайн-передачи** — например, на air-gapped серверы.
4. **Подписывайте bundle** — для аутентификации при передаче.
5. **Используйте `git bundle verify`** — перед использованием проверяйте целостность.

---

## Дополнительная информация

### Связанные темы

- [Git Attributes](./git_attributes.md) — export-ignore, export-subst для настройки архивов.
- [Git Tags](./git_tags.md) — архивы для релизов и интеграция с CI/CD.
- [Git Performance](./git_performance.md) — bundle URIs для кэширования и ускорения clone.
- [Синхронизация репозиториев](./git_synchronization.md) — офлайн-передача через bundle вместо push/pull.
- [Внутреннее устройство Git](./git_internals.md) — объекты, pack files и структура bundle.

### Официальные ресурсы

- **Git Archive Documentation:** [git-scm.com/docs/git-archive](https://git-scm.com/docs/git-archive)
- **Git Bundle Documentation:** [git-scm.com/docs/git-bundle](https://git-scm.com/docs/git-bundle)
- **Pro Git Book:** [git-scm.com/book/ru/v2/Git-инструменты](https://git-scm.com/book/ru/v2/Git-инструменты)
