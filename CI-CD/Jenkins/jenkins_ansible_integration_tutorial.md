# 7.5 Настройка Jenkins в связке с Ansible

**Цель данной статьи** - показать как настраивается Jenkins в связке с Ansible.

Предположим что у нас есть система с установленным Jenkins и мы хотели привязать IaaC в виде Ansible к ней.

**Условия:**
1.  Jenkins установлен со стандартными плагинами.
2.  Запуск всех пайплайнов будет происходить на той же машине где установлен Jenkins (стандартный build agent).

## Создание Pipeline

После установки Jenkins, вы можете создать новую build-работу.

1.  Нажмите "New Item".
2.  Введите имя и выберите **Pipeline**.

В свойствах проекта нас интересует секция **Pipeline**.

[Image: Jenkins Pipeline Configuration]

Jenkins, как и Gitlab, использует скрипт для запуска пайплайна по шагам. В отличие от Gitlab, Jenkins использует **Groovy** - полноценный язык программирования, который дает возможности более тонкой кастомизации работ.

## Цели

1.  Запустить Ansible и вывести его версию.
2.  Скачать Playbook с Github и запустить его.
3.  Постучаться в другую машину изнутри Jenkins.
4.  Использовать специальный плагин Ansible для всего вышеуказанного.

### 1. Запустить Ansible и вывести его версию

Пайплайны в Jenkins задаются через `Stage`, внутри которого перечисляются `Steps`.

**Pipeline Script:**
```groovy
pipeline {
    agent any // Указываем, что работа может выполняться на любом доступном агенте
    stages {
        stage('Deploy') { // Наш этап
            steps {
                // Шаги для выполнения
                sh 'ansible --version' // Выводим версию Ansible
            }
        }
    }
}
```

Сохраняем пайплайн и нажимаем **Build Now**. В `Console Output` билда вы увидите версию установленного Ansible.

### 2. Запуск Playbook с Github

Сначала создадим простой плейбук и разместим его на GitHub.

**playbook.yml:**
```yaml
- name: "Test playbook run"
  hosts: localhost
  tasks:
    - name: "Debug"
      ansible.builtin.debug:
        msg: "Test debug"
```

Теперь модифицируем наш пайплайн, чтобы он сначала скачивал репозиторий, а потом запускал плейбук. Для этого нам понадобится **SSH-ключ**, известный вашему GitHub аккаунту.

#### Настройка Credentials в Jenkins

1.  **Сгенерируйте SSH-ключ:**
    ```bash
    ssh-keygen -t rsa -f ~/.ssh/jenkins_github
    ```
2.  **Добавьте публичный ключ** (`jenkins_github.pub`) в ваш профиль на GitHub (`Settings -> SSH and GPG keys`).
3.  **Добавьте приватный ключ** в Jenkins:
    *   Перейдите в `Dashboard -> Manage Jenkins -> Credentials`.
    *   Нажмите `(global)` -> `Add Credentials`.
    *   **Kind**: `SSH Username with private key`.
    *   **Scope**: `Global`.
    *   **ID**: `github_key` (этот ID мы будем использовать в пайплайне).
    *   **Username**: ваш username на GitHub.
    *   **Private Key**: Выберите `Enter directly` и вставьте содержимое вашего **приватного** ключа (`jenkins_github`).

#### Модифицированный пайплайн

```groovy
pipeline {
    agent any
    stages {
        stage('Checkout') { // Этап скачивания кода
            steps {
                git branch: 'main',
                     url: 'git@github.com:your_username/your_repo.git', // Замените на ваш URL
                     credentialsId: 'github_key' // ID ключа из Jenkins Credentials
            }
        }
        stage('Deploy') {
            steps {
                sh 'ansible-playbook playbook.yml'
            }
        }
    }
}
```

После запуска Jenkins сначала выполнит `git clone`, а затем запустит плейбук в той же рабочей директории.

### 3. Подключение к удаленной машине

Теперь усложним задачу: заставим Ansible подключаться к другому хосту.

**hosts.ini:**
```ini
testmachine ansible_host=192.168.60.55 ansible_user=vagrant
```

**ansible.cfg:**
```ini
[defaults]
host_key_checking=false
```

**playbook.yml:**
```yaml
- name: "Test playbook run"
  hosts: all # теперь запускаем скрипты на удаленных хостах
  tasks:
    - name: "Debug"
      ansible.builtin.debug:
        msg: "Test debug"
```

Нам нужно, чтобы у Ansible был доступ к приватному ключу для подключения к `testmachine`. Мы можем использовать тот же ключ, что и для GitHub (если его публичная часть добавлена в `~/.ssh/authorized_keys` на `testmachine`) или создать новый.

Пайплайн нужно изменить, чтобы передать ключ в Ansible.

```groovy
pipeline {
    agent any
    stages {
        stage('Checkout') {
            steps {
                git branch: 'main',
                    url: 'git@github.com:your_username/your_repo.git',
                    credentialsId: 'github_key'
            }
        }
        stage('Deploy') {
            steps {
                // Оборачиваем шаги в withCredentials, чтобы получить доступ к ключу
                withCredentials([sshUserPrivateKey(credentialsId: 'github_key', keyFileVariable: 'PRIVATE_KEY_FILE')]) {
                    // Jenkins создаст временный файл с ключом и запишет путь к нему в переменную PRIVATE_KEY_FILE
                    sh 'ansible-playbook playbook.yml -i hosts.ini --private-key $PRIVATE_KEY_FILE'
                }
            }
        }
    }
}
```

### 4. Использование плагина Ansible

Для упрощения работы существует плагин **Ansible**.

1.  Установите плагин (`Manage Jenkins -> Manage Plugins -> Available -> Ansible`).
2.  Перезагрузите Jenkins.

Теперь пайплайн можно значительно упростить:

```groovy
pipeline {
    agent any
    stages {
        stage('Checkout') {
            steps {
                git branch: 'main',
                    url: 'git@github.com:your_username/your_repo.git',
                    credentialsId: 'github_key'
            }
        }
        stage('Deploy') {
            steps {
                // Используем шаг, предоставляемый плагином
                ansiblePlaybook(
                    playbook: 'playbook.yml',
                    inventory: 'hosts.ini',
                    credentialsId: 'github_key' // ID ключа для SSH-подключения
                )
            }
        }
    }
}
```

Плагин берет на себя всю работу по обработке credentials, что делает пайплайн чище и проще для понимания.

На этом все, всем спасибо за внимание!
