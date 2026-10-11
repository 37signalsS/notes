# GitHub Actions: Git-операции внутри воркфлоу

**Актуально для:** GitHub Actions, октябрь 2026 (actions/checkout v7, actions/create-github-app-token v3)

Коммиты, пуш и работа с историей из CI — источник большинства продакшен-инцидентов: рекурсивные прогоны, заблокированные push, потерянные теги. Тематический блок фиксирует механику `actions/checkout`, токен-авторизацию записи и паттерны бот-автоматизации.

## Определения

- **Shallow Clone**: Неполная копия репозитория (только последний коммит). Значение по умолчанию для `actions/checkout` (`fetch-depth: 1`) ради скорости.
- **persist-credentials**: Флаг checkout'а, управляющий сохранением токена аутентификации для последующих git-команд задачи (по умолчанию включён). Начиная с checkout v6 сам токен кладётся не в `.git/config`, а в отдельный файл под `$RUNNER_TEMP`, к которому git подключается директивой include; пост-шаг экшена удаляет его по завершении задачи.
- **Bot Commit**: Коммит, созданный воркфлоу от служебной идентичности (`github-actions[bot]`) с использованием встроенного или выделенного токена.
- **Рекурсивный триггер**: Ситуация, когда событие, порождённое воркфлоу (push бота), снова запускает тот же воркфлоу.
- **Installation Token**: Короткоживущий токен GitHub App (срок ~1 час), привязанный к установке приложения; аудируется и имеет гранулярные права.
- **Detached HEAD**: Состояние git, когда HEAD указывает на конкретный коммит, а не на ветку. Штатное состояние прогона `pull_request`: checkout берёт merge-коммит `refs/pull/N/merge`, поэтому сам по себе `git push` из него невозможен — сначала нужна ветка.
- **Bypass-актор**: Роль, команда, GitHub App или deploy key, которому ruleset разрешает обходить часть правил. `github-actions[bot]` в этот список не попадает.
- **Protected Tag / Ruleset**: Правило, требующее прав на создание/иззменение тегов по паттерну (механика защиты веток — в [Рабочих процессах Git](../Git/git_workflows.md#защита-веток-branch-protection), подробности о rulesets в [Rulesets](./rulesets.md)).

## Основные концепции

### Механика `actions/checkout`

```yaml
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0            # вся история всех веток и тегов
          # fetch-depth: 2          # последние 2 коммита (для diff-based логики)
          fetch-tags: true          # догрузить теги при мелком клоне
          persist-credentials: false
```

- `fetch-depth: 1` достаточно для сборки/тестов; полная история нужна: генерации changelog между тегами, `git describe`-версионированию, blame-подобной аналитике, работе с ветками релизов.
- Подводный камень shallow clone: теги не приходят автоматически — `git describe --tags` вернёт ошибку; лечится `fetch-depth: 0` либо `fetch-tags: true`. Второй вариант реально работает только начиная с checkout v6.0.2: в v4/v5 при `fetch-depth > 0` флаг игнорировался и теги всё равно не догружались ([actions/checkout#1471](https://github.com/actions/checkout/issues/1471), [#1662](https://github.com/actions/checkout/issues/1662)). Гарантированный результат на любой версии — `fetch-depth: 0`.
- **PR-прогон остаётся в detached HEAD**: checkout по умолчанию берёт merge-коммит `refs/pull/N/merge`, а не ветку, поэтому `git push` падает с `fatal: You are not currently on a branch`. Для записи в ветку PR укажите `ref: ${{ github.head_ref }}`; для тегового триггера создавайте ветку явно (`git switch -c`).
- **checkout v7 по умолчанию отказывается клонировать код форк-PR** в прогонах `pull_request_target` (и в `workflow_run`, запущенном по `pull_request`-событию) — так закрыт распространённый вектор «pwn request». Opt-in только после ревью рисков: `allow-unsafe-pr-checkout: true`.
- Для монорепозиториев комбинация `fetch-depth: 1` + `sparse-checkout` сокращает время checkout с минут до секунд (скоростные аспекты — в [Оптимизации](./Optimization.md)).
- `lfs: true` подключает Git LFS для бинарных артефактов репозитория.

### `persist-credentials` и безопасность записи

- По умолчанию checkout сохраняет токен для git-команд задачи — последующие `git push` работают «магически». С checkout v6 сам токен лежит уже не в `.git/config`, а в отдельном файле под `$RUNNER_TEMP`, но безопасность от этого не меняется: любой шаг задачи может выполнить авторизованные git-операции от имени этого токена, что опасно на недоверенном коде (форк-PR).
- Безопасный шаблон: `persist-credentials: false` + явная авторизация push через отдельный токен в URL remote или credential helper только на нужном шаге.
- Встроенный `GITHUB_TOKEN` подчиняется политике permissions воркфлоу (иерархия токенов — в [Управлении секретами](./secrets_management.md)).

### Права на запись: `permissions` и установка App

Push — операция записи, и права приходят с двух независимых сторон; упустив любую из них, вы получите отказ в самом конце прогона, на шаге `git push`.

- **`GITHUB_TOKEN`** — токену нужен явный блок на уровне воркфлоу или задачи:

  ```yaml
  permissions:
    contents: write
  ```

  Без него push отклоняется с `Resource not accessible by integration`. Для новых репозиториев режим по умолчанию — read-only, поэтому полагаться на дефолт нельзя; права расширяются точечно только на той задаче, где нужен push ([Управление секретами](./secrets_management.md#управление-github_token)).
- **Токен GitHub App** — права задаются установке приложения (`Contents: Read and write`), а экшен `actions/create-github-app-token` дополнительно умеет сузить выдаваемый токен входом `permission-contents: write`: на задачу попадает ровно одно право, а не весь набор установки.
- Токен, переданный в `token:` checkout'а, — тот, которым будет авторизован `git push`; блок `permissions` воркфлоу на него не влияет.

### Антирекурсия: кто кого триггерит

| Токен | Push создаёт новый прогон? |
| :--- | :--- |
| `GITHUB_TOKEN` (встроенный) | **Нет** — события от него не триггерят воркфлоу (защита платформы от петель) |
| PAT | Да |
| GitHub App installation token | Да |

Следствия:
- Бот на `GITHUB_TOKEN` не зациклится никогда, но его коммит **не запустит** downstream CI — это нужно учитывать (запускать следующий этап явно через `workflow_dispatch`/API либо использовать App-токен).
- При записи под PAT/App добавляйте страховку: условие `if: github.actor != 'my-release-bot[bot]'` в триггерном воркфлоу либо маркер `[skip ci]` в сообщении коммита.
- `[skip ci]`/`[ci skip]`/`[no ci]` в заголовке сообщения коммита отменяет запуск push/pull_request воркфлоу (полный список способов пропуска, включая трейлер `skip-checks: true`, — в [Событиях](./Events_Jobs_Steps.md#пропуск-воркфлоу-skip-workflow)).

### Идентичность бот-коммитов

```bash
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
```

- Стандартная идентичность делает происхождение коммитов очевидным в UI и фильтрах (`author:app/github-actions`); аватар бота отображается корректно.
- Подпись GPG бот-коммитов нетривиальна: коммит, созданный обычным `git push` из воркфлоу, остаётся **без подписи**, и политика `Require signed commits` его отклонит. Три рабочих пути:
  1. **Commits API вместо git**: коммит, созданный от токена App (или `GITHUB_TOKEN`) через Commits API, GitHub подписывает сам и помечает `verified`. Условие документации: запрос аутентифицирован токеном бота и не содержит кастомных `author`/`committer` — любое кастомное поле снимает подпись.
  2. **Свой ключ**: GPG- или SSH-ключ бота в секретах репозитория + `git config commit.gpgsign true` (и `gpg.format=ssh` / `user.signingkey` для SSH). Подпись проверяется нормально, но ключ придётся ротировать вместе с секретами.
  3. **Исключить ботов** из требования подписи — осознанный компромисс, обычно для внутренних репозиториев.

### Запись в защищённую ветку

`GITHUB_TOKEN` не может обойти Branch Protection/Rulesets. Важно, что проверяется личность самого токена, а не запустившего workflow: админ, нажавший `workflow_dispatch`, не передаёт своему `GITHUB_TOKEN` свои права на bypass. Легальные пути:

1. **GitHub App** (рекомендуется): installation token добавляется в bypass-лист ruleset (там он виден как GitHub App), права гранулярны, все действия аудируются.
2. **PAT** пользователя с ролью, имеющей bypass: просто, но наследует личные права и уходит вместе с сотрудником.
3. **SSH deploy key** с правом записи — узкая альтернатива для одного репозитория: пробрасывается в checkout входом `ssh-key`, а в bypass-лист ruleset добавляется как актор типа `DeployKey`.
4. **PR-модель**: бот пушит в рабочую ветку и открывает Pull Request — защиту никто не обходит, ревью сохраняется. Предпочтительно для изменений, видимых людям (обновления зависимостей, версии).
5. Временное снятие защиты из скрипта — антипаттерн (гонки, отсутствие аудита).

### Гонка push: когда бот и человек пишут одновременно

Бот-коммит — это обычный push, и он падает по тем же причинам: пока задача собиралась, в ветку мог уйти чужой коммит, и remote отвечает `! [rejected] (non-fast-forward)`. Два уровня защиты:

- **Сериализация до push**: `concurrency`-группа, отменяющая устаревшие прогоны бота ([Оптимизация](./Optimization.md#5-контроль-одновременных-запусков-concurrency)):

  ```yaml
  concurrency:
    group: bot-push-${{ github.ref }}
    cancel-in-progress: false    # не отменять посреди коммита, а ставить в очередь
  ```

- **Повтор на месте** — rebase на актуальный remote с обратным отсчётом (иллюстративный шаблон):

  ```bash
  for i in 1 2 3; do
    git pull --rebase --autostash origin "$BRANCH" && git push && break
    sleep $((i * 5))
  done
  ```

  При реальном конфликте повтор не поможет — правку придётся пересобирать заново. Перезапись истории в общей ветке не нужна ни при каком раскладе; если перезапись неизбежна на своей ветке — только `--force-with-lease` ([синхронизация Git](../Git/git_synchronization.md#стратегии-отправки-изменений-push)).

---

## Практические сценарии

### Сценарий 1: Автокоммит от бота (bump версии)

**Предварительные требования**: GitHub App установлен в репозиторий и имеет право `Contents: Read and write`; Client ID приложения — в переменной `APP_CLIENT_ID`, приватный ключ — в секрете `APP_PRIVATE_KEY`.

```yaml
jobs:
  bump:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/create-github-app-token@v3
        id: app-token
        with:
          client-id: ${{ vars.APP_CLIENT_ID }}
          private-key: ${{ secrets.APP_PRIVATE_KEY }}
          permission-contents: write   # только одно право вместо всего набора установки
      - uses: actions/checkout@v7
        with:
          token: ${{ steps.app-token.outputs.token }}
          persist-credentials: true        # удобно для единственного push ниже
      - run: npm version patch --no-git-tag-version
      - name: Commit and push
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git commit -am "chore(release): bump version [skip ci]"
          git push
```

- Каждый параметр: App-токен пробрасывается прямо в checkout — push авторизуется им; идентичность задаётся явно до коммита; `[skip ci]` страхует от лишних прогонов при переходе на PAT. В v3 экшена вход `app-id` помечен как устаревший — вместо него `client-id`; на self-hosted раннере требуется Actions Runner ≥ 2.327.1.
- **Валидация**: `git log -1 --format='%an %ae'` в ветке показывает `github-actions[bot]`; вкладка Actions не содержит нового прогона от этого коммита (токен App, как и PAT, триггерит — поэтому `[skip ci]`; при желании запустить downstream CI уберите маркер).

### Сценарий 2: Бот открывает PR вместо прямого push

```yaml
      - name: Create PR
        env:
          GH_TOKEN: ${{ steps.app-token.outputs.token }}
        run: |
          BRANCH="bot/regen-$(date +%Y%m%d%H%M)"
          git checkout -b "$BRANCH"
          make regenerate && git commit -am "chore: regenerate clients" || exit 0
          git push origin "$BRANCH"
          gh pr create \
            --title "Regenerate API clients" \
            --body "Автоматическая регенерация. Не мержить без ревью diff." \
            --label automerge-candidate \
            --base main --head "$BRANCH"
```

- PR-модель сохраняет обязательные проверки и ревью; лейбл `automerge-candidate` позволяет авто-мерж после зелёного CI отдельным регламентом.
- **Валидация**: PR появляется со списком проверок; diff ограничен сгенерированными файлами; повторный прогон создаёт новую ветку, а не падает на существующей.
- **Очистка**: слитые bot-ветки удаляются правилом автоматического удаления head-веток (Settings → General → Pull Requests).

### Сценарий 3: Диагностика «воркфлоу не запустился» после бот-push

```bash
# проверить автора последнего коммита и маркер пропуска
git log -1 --format='%an|%s'
# → github-actions[bot]|chore: bump version [skip ci]
# вывод: прогон отсутствует легально — либо GITHUB_TOKEN/App+skip,
# либо маркер [skip ci]. Решение: убрать маркер или триггерить вручную
gh workflow run deploy.yml --ref main    # явный запуск следующего этапа
```

- Типовая ловушка: команда мигрирует бота с `GITHUB_TOKEN` на PAT, ожидая автозапуска CI, но в сообщении остаётся `[skip ci]`.
- **Валидация**: после удаления маркера следующий бот-коммит порождает прогон; история прогонов фильтруется по `event=push`.

Расширенная диагностика того же прогона:

```bash
git status -sb                                  # на какой ветке/состоянии вообще находимся
# → ## main...origin/main
git log -1 --format='%an <%ae> %G?'             # автор и статус подписи
# → github-actions[bot] <...> N                 # N — подписи нет, G — хорошая
gh run list --limit 5 --json event,displayTitle,conclusion \
  --jq '.[] | "\(.event) \(.displayTitle) \(.conclusion)"'
# → push chore: bump version skipped
```

- `%G?` отвечает на вопрос «а почему политика signed commits ругается» прямо в конвейере, не заходя в UI.
- Если `gh run list` показывает `skipped` — коммит увидел платформа, но попал под пропуск-инструкцию; строк от `push` нет вовсе — значит, push не произошёл или авторизован токеном, который события не порождает.

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `! [remote rejected] (protected branch hook protection)` / `GH013: Repository rule violations found` | Запись в защищённую ветку токеном без bypass | App/PAT/deploy key в bypass-листе ruleset либо PR-модель |
| `403` / `Resource not accessible by integration` на `git push` | У `GITHUB_TOKEN` нет `permissions: contents: write` | Добавить блок permissions точечно на задачу |
| После бот-коммита CI молчит | GITHUB_TOKEN не триггерит прогоны; либо `[skip ci]` | Явный `workflow_dispatch`/App-токен; проверить сообщение коммита |
| `Authentication failed for 'https://github.com/'` / `could not read Username` | `persist-credentials: false` без явного токена на шаге push | Пробросить token в checkout или настроить credential helper только на шаге |
| `! [rejected] (non-fast-forward)` | Гонка: в ветку ушёл чужой коммит, пока задача собиралась | `git pull --rebase` + повтор push; сериализовать бота `concurrency`-группой |
| `fatal: You are not currently on a branch` | Detached HEAD прогона `pull_request`/тега | `ref: ${{ github.head_ref }}` в checkout либо `git switch -c <ветка>` |
| `fatal: detected dubious ownership in repository` | Путь не в `safe.directory` (запуск git от другого пользователя / вне checkout-шага) | `git config --global --add safe.directory "$GITHUB_WORKSPACE"`; у checkout это делается сам (`set-safe-directory: true`) |
| Push из форк-PR отклонён (403) | Штатная модель доверия: форк-прогоны получают read-only токен | Привилегированную часть вынести в `workflow_run` ([пример](./Events_Jobs_Steps.md#сценарий-6-безопасная-постобработка-форк-pr-workflow_run)) |
| `git describe` падает `No names found` | Shallow clone без тегов | `fetch-depth: 0` (гарантированно) либо `fetch-tags: true` на checkout ≥ v6.0.2 |
| Diff пустой, commit падает | Изменений нет (регенерация ничего не поменяла) | `|| exit 0` на commit, раннее завершение задачи |
| Коммит от «неожиданного» автора | Идентичность не настроена глобально в задаче | Задать `user.name/user.email` перед первым commit |
| Checkout занимает минуты на монорепо | Полная история без нужды | `fetch-depth: 1` + `sparse-checkout` |

## Лучшие практики

1. Иерархия выбора токена для записи: GitHub App > PAT > `GITHUB_TOKEN`; каждый следующий уровень — больше прав и риска.
2. Для человекочитаемых изменений всегда PR-модель: защита веток не отключается, аудит естественный.
3. Явно задавайте bot-идентичность каждого коммита — фильтруемость и честный UI.
4. `persist-credentials: false` по умолчанию во всех недоверенных контекстах; точечное включение там, где push действительно нужен.
5. Стройте конвейеры так, чтобы поведение не зависело от того, триггерит ли бот-коммит CI: связывайте этапы через `needs`/`workflow_call`, а не через цепочки push.
6. Никогда не коммитьте секреты даже «временно»; ротация ключа App хранится только в секретах репозитория.
7. Права — только точечно: `permissions: contents: write` на конкретной задаче, для App-токена `permission-contents: write`. Ни `write-all`, ни полагание на настройки организации.
8. Сериализуйте бот-записи в общие ветки `concurrency`-группой и снимайте остаточные гонки `pull --rebase` с повтором — это дешевле, чем разгребать потерянные коммиты.
9. Решите вопрос с подписями коммитов до первого продакшен-конвейера: политика `Require signed commits` иначе остановит бот-пуш посреди ночи.
10. Перед коммитом проверяйте состояние репозитория (`git status -sb`) — это ловит и detached HEAD, и неожиданно сменённую ветку за одну команду.

## Дополнительная информация

- **[Управление секретами](./secrets_management.md)** — иерархия токенов и permissions.
- **[События, Задачи и Шаги](./Events_Jobs_Steps.md)** — пропуск ворклоу и фильтры событий.
- **[Управление релизами](./Release_Management.md)** — bump версии в составе релизного конвейера.
- **[Оптимизация воркфлоу](./Optimization.md)** — ускорение checkout в монорепозиториях и контроль одновременных запусков.
- **[Синхронизация Git](../Git/git_synchronization.md)** — fetch/pull/push, безопасный force-push.
- **[Устранение неполадок Git](../Git/git_troubleshooting.md)** — диагностика отказов push и аутентификации.
- **[Основы Git](../Git/git_basics.md)** — базовые операции clone/fetch/push.
