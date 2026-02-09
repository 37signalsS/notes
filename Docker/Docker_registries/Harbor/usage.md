# Работа с Harbor

## 1. Аутентификация

```bash
docker login harbor.yourdomain.com
# Username: admin
# Password: <YourAdminPassword>
```

## 2. Тегирование и отправка образа

```bash
# В Harbor образы организованы по проектам (например, 'library')
docker tag my-app:latest harbor.yourdomain.com/library/my-app:v1
docker push harbor.yourdomain.com/library/my-app:v1
```

## 3. Получение образа

```bash
docker pull harbor.yourdomain.com/library/my-app:v1
```
