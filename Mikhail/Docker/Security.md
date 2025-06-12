https://docs.docker.com/engine/security/

Запуск без root-доступа
```sh
docker run --user 1000:1000 my-image
```
Только для чтения
```sh
docker run --read-only my-image
```
Удалить все cap-привилегии ядра
```sh
docker run --cap-drop=ALL my-image
```
Использовать seccomp-профиль
```sh
docker run --security-opt seccomp=default.json my-image
```
Отключить сеть
```sh
docker run --network=none my-image
```

Также стоит:
• Настроить AppArmor / SELinux  
• Запретить монтирование Docker сокета  
• Ограничить доступ к /proc, /sys