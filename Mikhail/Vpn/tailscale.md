# **Настройка tailscale на Linux**

``` sh
sudo tailscale up --login-server https://headscale.magicfun.nnstd.dev
```

``` sh
headscale nodes register --user misha --key mkey: вставляю ключ с сайта
```

 На клиентском устройстве перед tailscale up прописываю 

``` sh
 sudo tailscale set --exit-node=kaguya
```
# **Настройка tailscale на Android**

1. В настройках выбираем альтернативный сервер

2. Вводим адрес

3. Копируем mkey с сайта 

4. Регаемся на rei

5. Log in в приложении

# **Удаление неактуальных записей из headscale**

``` sh
headscale nodes ls 
```

``` sh
headscale nodes delete -i номер подключения
```
# **Добавление нового пользователя** 

``` sh
headscale users create имя
```

Добавляем в соответствующую группу пользователя в файле acl.json

``` sh
docker compose restart
```



