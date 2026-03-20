# Git Other Conventions — другие соглашения

## Определения

Различные файлы-соглашения, связанные с Git, но не являющиеся стандартными фичами.

---

## Другие соглашения

### .gitkeep

* **Статус:** Соглашение, **не фича Git**.
* **Назначение:** Git не отслеживает пустые директории. Файл `.gitkeep` (или любой другой) помещается в пустую папку, чтобы Git имел что отслеживать.
* **Имя произвольное:** Может называться как угодно, `.gitkeep` — конвенция.

### .gitconfig (в репозитории)

* **Назначение:** Предлагаемая конфигурация для разработчиков.
* **Ограничение:** Git **не загружает** такие файлы автоматически (безопасность).
* **Использование:** Проекты включают инструкции для ручной настройки:
  ```bash
  git config include.path ../.gitconfig
  ```
* **Применение:** Монорепозитории, проекты со специфичными настройками Git.

### .gitsigners / allowedSigners

* **Назначение:** Файлы с доверенными ключами подписи (GPG/SSH) для верификации коммитов.
* **Использование:** Linux kernel и другие проекты с trusted contributors.
* **Настройка:** `git config gpg.ssh.allowedSignersFile <файл>` для `git log --show-signature`.

### .gitreview

* **Назначение:** Конфигурация интеграции с Gerrit.
* **Проекты:** OpenStack, Android, Eclipse.
* **Формат:**
  ```ini
  [gerrit]
  host=review.opendev.org
  port=29418
  project=openstack/nova.git
  defaultbranch=master
  ```
* **Использование:** `git review` читает файл и пушит коммиты в Gerrit для ревью.

### .gitlint

* **Назначение:** Конфигурация линтера сообщений коммитов.
* **Пример:**
  ```ini
  [general]
  ignore=body-is-missing

  [title-max-length]
  line-length=72
  ```

### .jj/

* **Назначение:** Директория состояния Jujutsu (git-совместимая VCS).
* **Особенности:** Сосуществует с `.git/`, уважает все магические файлы Git (.gitignore, .gitattributes, .mailmap).

---

## Связанные документы

- **Обзор**: [git_special_files_overview.md](./git_special_files_overview.md)
- **Git Commit Template**: [git_commit_template.md](./git_commit_template.md)
