Для получения более подробной информации о SSH, генерации ключей и управлении ими, обратитесь к основному документу [SSH (Secure Shell)](../Linux/Security/ssh.md).

### Работа с SSH-ключами

**Создание нового SSH-ключа:**

```bash
ssh-keygen -t ed25519 -C "ваш@email.com" -f ~/.ssh/id_ed25519_project
```

**Добавление ключа в ssh-agent:**

```bash
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519_project
chmod 600 ~/.ssh/id_ed25519_project
chmod 700 ~/.ssh
```

**Управление несколькими ключами** (`~/.ssh/config`):

```ini
# Стандартный ключ
Host github.com
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519

# Ключ для конкретного проекта
Host project-alias
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519_project
```
Клонирование с псевдонимом: `git clone git@project-alias:user/repo.git`
