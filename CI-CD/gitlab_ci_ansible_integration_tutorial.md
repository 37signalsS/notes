# 7.4 Установка и использование GitLab Runner с Ansible

## Введение

Эта практика выполняется у вас локально.

Сегодня мы с вами познакомимся с установкой и оперированием GitLab Runner вместе с Ansible. Для этого мы установим GitLab Runner и используем его для запуска простого плейбука Ansible.

## Установка раннера

Инструкция по установке Gitlab Runner находится в настройках проекта, в разделе CI/CD. Вы можете также установить раннер глобально, в настройках самого GitLab в том же разделе. Но процесс установки самого раннера не отличается никак, поэтому мы установим раннер локально для проекта.

Выбираем пункт С/СО из настроек проекта. Если вы не видите настроек, скорее всего вы не Owner проекта, поставьте права выше или зайдите от администратора.

[Image: GitLab Project Settings CI/CD]

В разделе “Cl/CD" мы видим раздел Gitlab runners и можем кликнуть Expand, чтобы развернуть его.

[Image: GitLab Runners Section]

Мы будем устанавливать раннер вручную, кликнув на "Install Gitlab Runner and ensure it's running". Это откроет страницу с инструкциями которым мы будем следовать.

[Image: GitLab Runner Installation Instructions]

Давайте залогинимся по ssh на машину, содержащую в себе установленный Ansible и установим раннер туда. Для установки раннера нам обязательно понадобится пользователь с `sudo`.

Мы воспользуемся самым простым путем установки раннера - просто добавим maintained пакет с их репозитория.

```bash
# Для Debian/Ubuntu/Mint
curl -L "https://packages.gitlab.com/install/repositories/runner/gitlab-runner/script.deb.sh" | sudo bash

# Для RHEL/CentOS/Fedora
curl -L "https://packages.gitlab.com/install/repositories/runner/gitlab-runner/script.rpm.sh" | sudo bash
```

**ВНИМАНИЕ!** B официальном репозитории Ubuntu уже содержится runner старой версии, поэтому для установки раннера именно из репозитория gitlab надо запинить гитлаб с более высоким приоритетом. Делается это следующим образом.

```bash
cat <<EOF | sudo tee /etc/apt/preferences.d/pin-gitlab-runner.pref
Explanation: Prefer GitLab provided packages over the Debian native ones
Package: gitlab-runner
Pin: origin packages.gitlab.com
Pin-Priority: 1001
EOF
```

Таким образом `apt` будет ставить не раннер по умолчанию, а именно тот что вы хотите. Для RHEL, Fedora и прочих не Debian дистрибутивов ничего такого делать не надо.

После добавления репозитория мы можем просто запустить команду `apt-get` или `yum` для установки раннера.

```bash
# Для Debian/Ubuntu/Mint
sudo apt-get install gitlab-runner

# Для RHEL/CentOS/Fedora
sudo yum install gitlab-runner
```

После установки проверим статус командой:

```bash
ps aux | grep runner
```

Либо:

```bash
systemctl status gitlab-runner
```

В обоих случаях runner должен отображаться как `running`. На моем опыте единственная ошибка, которую я получал на данном этапе - недостаточно разрешений у пользователя, либо закрытые для записи папки, в которых раннер хранит артефакты и конфигурацию (`/home/gitlab-runner` и `/etc/gitlab-runner/`). Эти папки должны быть открыты для записи.

После установки раннера время настроить и зарегистрировать его в gitlab.

## Регистрация раннера

Регистрация раннера необходима для установки соединения между ним и GitLab, чтобы мы могли его использовать при билде своих проектов. Gitlab предоставляет подробную инструкцию и сравнения всех возможных раннеров.

### Selecting the executor

[Table: Executor Comparison]

Если вы новичок в пайплайнах CI, я рекомендую установить раннеры изначально в состояние `Shell` или `Ssh`, для легкости отладки.

Мы будем использовать регистрацию раннера в режиме `Shell`. В этом режиме все выполнение скриптов происходит непосредственно на машине. Очень легкий для отладки режим, потому что всегда есть возможность посмотреть различные логи, и что-то подкрутить руками в машине. Не рекомендуется для продакшена, потому что какие нибудь плохо написанные пайплайны сборки могут сломать саму машину и придется начинать все заново.

Запускаем команду:

```bash
sudo gitlab-runner register --url $REGISTRATION_URL --registration-token $REGISTRATION_TOKEN
```

Где вам нужно заменить `$REGISTRATION_URL` на ваш URL GitLab (например `https://gitlab.slurm.io/`) а `$REGISTRATION_TOKEN` на ваш токен регистрации (отображается в разделе registration token в секции CI/CD).

Команда запускается в интерактивном режиме и ожидает от вас подтверждения вопросов.

1.  **GitLab instance URL**: `[https://gitlab.slurm.io/]:` - Жмите Enter.
2.  **Registration token**: Просто Enter.
3.  **Description for the runner**: `[node-1.s013895.slurm.io]:` - Можете написать что хотите, по умолчанию там просто hostname машины. Я рекомендую писать какие-то значимые описания для продакшена, например `Gitlab in cluster east-sa (east-sa connections)` или `Webpacker`.
4.  **Tags for the runner**: `(comma-separated):` - Это те «маркеры», по которым вы можете запускать работы в Gitlab. Для нашей тестовой машины я поставлю тег `test`.
5.  **Executor**: `docker-ssh, shell, docker+machine, ...` - Я выберу метод `shell`.

После этого мы видим жизнеутверждающую надпись, указывающую нам что раннер готов к работе.

## Сам GitLab

После установки и регистрации раннера вы увидите его в своем проекте в той же вкладке Cl/CD.

[Image: Available specific runners]

Если его не видно, то скорее всего, ваш фаервол блокирует входящие соединения. Попробуйте открыть порты `8093` или `22`.

Gitlab использует файлы `.gitlab-ci.yml`, представляющие yml файлы, с описанием шагов пайплайна.

Переходим на главную проекта, если вы его только создали то он пуст. Нажимаем `New file`, выбираем `.gitlab-ci.yml` и используем шаблон `5-Minute-Production-App` для примера.

### Структура `.gitlab-ci.yml`

```yaml
# Этот файл только пример, но мы рассмотрим его чтобы понять структуру пайплайнов гитлаба
include:
  # здесь размещаются дополнительные скрипты, они определяют дополнительные условия для пайплайнов,
  # чтобы предотвратить дублирование скриптов и работают аналогично include тасков в Ansible
  - template: 'Workflows/Branch-Pipelines.gitlab-ci.yml'
  - template: 'Jobs/Build.gitlab-ci.yml'

# Stages определяют стадии пайплайна, например работы по сборке, поднятие серверов, деплой, запуск тестов, удаление серверов.
stages:
  - build
  - test
  - provision
  - deploy
  - destroy

# B переменных содержатся значения, которые можно использовать в скриптах. Обратите внимание на ${имя_переменной}
# гитлаб подставит значения в эти переменные во время выполнения
variables:
  TF_ADDRESS: ${CI_API_V4_URL}/projects/${CI_PROJECT_ID}/terraform/state/${CI_COMMIT_REF_SLUG}
  TF_VAR_ENVIRONMENT_NAME: ${CI_PROJECT_PATH_SLUG}_${CI_PROJECT_ID}_${CI_COMMIT_REF_SLUG}

# это непосредственно работа в пайплайне, как и Task в Ansible начинается с имени
terraform_apply:
  stage: provision # определяем на какой стадии данная работа
  image: registry.gitlab.com/gitlab-org/5-minute-production-app/deploy-template/stable # для docker runner мы можем определить контейнер, содержащий все нужные компоненты
  resource_group: terraform # job'ы складывают артефакты в определенные места на раннере, чтобы избежать коллизий мы определяем ресурсную группу
  before_script:
    - cp /deploy.sh .
  script:
    - gitlab-terraform init
    - gitlab-terraform plan
    - gitlab-terraform plan-json
    - gitlab-terraform apply

deploy:
  stage: deploy
  # ...
  artifacts:
    reports:
      dotenv: deploy.env # здесь мы определяем так называемые артефакты скрипта - файлы, образовавшиеся в результате работы скрипта.
  environment:
    name: $CI_COMMIT_REF_SLUG
    url: $DYNAMIC_ENVIRONMENT_URL
    on_stop: terraform_destroy
```

### Наш простой пайплайн

Мы используем знания из шаблона, чтобы сделать свой шаблон, который просто запустит скрипт, показывающий нам версию Ansible.

**.gitlab-ci.yml:**
```yaml
stages:
  - provision # оставим только один шаг

ansible_run:
  stage: provision # запускаем работу в provision
  tags:
    - test # этот тег нужен для того чтобы отправить работу на конкретную машину с ansible
  script:
    - ansible --version # сам скрипт который покажет нам версию
```

После коммита файла в GitLab вы увидите запуск пайплайна. Если кликнуть по нему, можно увидеть лог выполнения.

### Запуск Ansible Playbook

Теперь напишем простой плейбук и запустим его с помощью Ansible.
Наш плейбук будет состоять из файла `hosts`, `ansible.cfg` и `playbook.yml`.

**Внимание!** Скорее всего раннер не будет включать в себя программу `sshpass`, необходимую для авторизации по паролю в ssh. Тогда ее надо будет установить.

**hosts.ini:**
```ini
testnode ansible_host=node-2.ваш_пользователь ansible_ssh_pass=ваш_пароль ansible_user=ваш_пользователь
```

**ansible.cfg:**
```ini
[defaults]
host_key_checking = False # отключим проверку ключей чтобы не ловить ошибки
```

**playbook.yml:**
```yaml
- name: "Ping hosts"
  hosts: all
  gather_facts: false
  tasks:
    - name: "Ping host"
      ansible.builtin.ping:
```

**Измененный .gitlab-ci.yml:**
```yaml
stages:
  - provision

ansible_run:
  stage: provision
  tags:
    - test
  script:
    - ansible-playbook playbook.yml -i hosts.ini
```

Стоит понимать, что все работы запускаются из папки `/home/gitlab-runner/`. Таким образом пути, используемые в скриптах (например ssh ключи), надо строить оттуда, а еще лучше использовать абсолютные пути.

## SSH ключи в раннере

Запускать работы Ansible, явно указывая пароль в `hosts.ini`, небезопасно. Передадим ключ из GitLab.

1.  Сгенерируйте или получите ваш SSH ключ (`~/.ssh/id_rsa`).
2.  Скопируйте **приватную** часть ключа.
3.  В GitLab, в разделе `CI/CD` -> `Variables`, добавьте новую переменную.
    *   **Key**: `PRIVATE_KEY`
    *   **Value**: (вставьте ваш приватный ключ)
    *   **Type**: `Variable`
    *   **Flags**: `Masked` (желательно)

Мы не можем использовать тип `FILE`, по причине проверки SSH клиентом пермишенов ключей.

Теперь изменим наш пайплайн:

**.gitlab-ci.yml:**
```yaml
stages:
  - provision

ansible_run:
  stage: provision
  tags:
    - test
  script:
    - echo "${PRIVATE_KEY}" > "$(pwd)/private" # сохраняем ключ в файл private
    - chmod 600 "$(pwd)/private" # ставим нужные пермишены (было 700, но 600 более корректно для ключей)
    - ansible-playbook playbook.yml -i hosts.ini --private-key "$(pwd)/private" # подсовываем ключ в ansible
```

### Другие способы управления ключами:
1.  Хранить приватные ключи в зашифрованном виде в репозитории (например, с Ansible Vault).
2.  Использовать [Keepass](https://keepass.info/) и плагины для интеграции.

Спасибо за внимание!
