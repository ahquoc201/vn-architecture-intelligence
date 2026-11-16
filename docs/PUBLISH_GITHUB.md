# Đưa repo local lên GitHub (thực hiện trên tài khoản của bạn)

Repository ở trạng thái mã nguồn local, chưa được tạo trên tài khoản GitHub của bạn.

1. Giải nén vào thư mục mong muốn và kiểm tra lại những thông tin muốn công khai.
2. Trong thư mục repo:

```powershell
git init
git add .
git commit -m "chore: bootstrap vn architecture intelligence 0.1.0"
# Nếu đã cài và đăng nhập GitHub CLI:
gh repo create vn-architecture-intelligence --private --source . --remote origin --push
```

3. Kiểm tra Actions → CI. Khi sẵn sàng công khai và đã xác minh quyền sử dụng nội dung, đổi visibility thành Public trong GitHub Settings.
4. Để quản lý nội dung mới: mở `Source proposal` issue; gửi PR có bảng review theo `CONTRIBUTING.md`.

**Không điền thông tin tài khoản, token, địa chỉ nhà, hồ sơ khách hàng hay PDF sách có bản quyền vào kho công khai.**
