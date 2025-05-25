# **Переходим в папку которую хотим опубликовать**

``` sh
cd dots
```
```sh 
git init 
```

``` sh
git config --global --add safe.directory /home/user/dots
```

``` sh
git config --global user.email "..."
```

``` sh
git config --global user.name "..."
```
Добавить удаленный репозиторий и дать ему имя/алиас:

```sh 
git remote add origin <url>
```

``` sh
sudo git add .
```

``` sh
sudo git commit -m "test"
```

``` sh
sudo git push --set-upstream origin master
```
(--set-upstream origin master, это необходимо дабы связать удаленный репозиторий/ветку с алиасом origin с локальной веткой master)

# **Удалить папку/файл** 

``` sh
git rm -rf
```
# **В случае конфликта версий:**

``` sh
git pull
```

``` sh
git merge
```

Еще вариант  

``` sh
git config pull.rebase false
```

и повторить шаги выше

# **Доступ/пуш дотов через ssh**

``` sh
ssh-keygen -t ed25519 -C "email" -f ~/.ssh/id_ed25519_abc
```

``` sh
su 
```

``` sh
eval "$(ssh-agent -s)"
```

``` sh
ssh-add <путь до приватного ключа>
```


Если был до этого https 

```sh
git remote set-url origin <ссылка>
```

Вставить оба ключа в .ssh

``` sh
chmod 600 ~/.ssh/id_ed25519
```

``` sh
chmod 700 ~/.ssh
```

# **Изменение ssh ключа для репозитория**

```sh
ssh-keygen -t ed25519 -C "email" -f ~/.ssh/id_ed25519_obsidian
```

```sh
su 
```

``` sh
eval "$(ssh-agent -s)"
```

``` sh
ssh-add <путь до приватного ключа>
```

``` sh
chmod 600 ~/.ssh/id_ed25519_obsidian
```

``` sh
chmod 700 ~/.ssh
```

Переименовываемым удаленный репозиторий

```sh
git remote rename origin obsidian
```

```sh
cd .ssh
```

```sh
micro config
```

После origin можно через пробел указать и другие алиасы, которые будут использовать один ssh ключ

```
Host origin
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519

Host obsidian #алиас/псевдоним удаленного репозитория по умолчанию origin
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519_obsidian
```

Далее добавляем новый удаленный репозиторий, в конфиге которого указан другой ключ ssh

```sh
git remote add obsidian git@obsidian:37signalsS/my-notes.git
```

```sh
git push --set-upstream obsidian master
```
