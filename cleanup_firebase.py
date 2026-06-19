import time
from datetime import datetime, timedelta, timezone
import firebase_admin
from firebase_admin import credentials, firestore

# --- CONFIGURATION ---
BATCH_SIZE = 100  # Số lượng xóa mỗi mẻ

cred = credentials.Certificate("serviceAccountKey.json")
try:
    firebase_admin.get_app()
except ValueError:
    firebase_admin.initialize_app(cred)
    
db = firestore.client()

def delete_old_docs(collection_name, days_to_keep, status_field=None, status_values=None, require_zero_coins=False):
    print(f"\n🧹 Bắt đầu dọn dẹp collection [{collection_name}] cũ hơn {days_to_keep} ngày...")
    cutoff_time = datetime.now(timezone.utc) - timedelta(days=days_to_keep)
    
    col_ref = db.collection(collection_name)
    
    docs = col_ref.stream()
    docs_to_delete = []
    
    for doc in docs:
        data = doc.to_dict()
        
        # Nếu có lọc theo status
        if status_field and status_values:
            if data.get(status_field) not in status_values:
                continue
                
        # [NEW]: Kiểm tra bắt buộc tài khoản phải hết coin mới được xóa
        if require_zero_coins:
            coins = data.get('coins', 0)
            try:
                if int(coins) > 0:
                    continue
            except (ValueError, TypeError):
                pass
                
        # Lấy thời gian update cuối cùng của document (chính xác 100% từ Firestore metadata)
        update_time = doc.update_time
        if update_time and update_time < cutoff_time:
            docs_to_delete.append(doc.reference)
            
    if not docs_to_delete:
        print(f"✅ Không có document rác nào cần xóa trong [{collection_name}].")
        return
        
    print(f"🗑️ Tìm thấy {len(docs_to_delete)} document cũ trong [{collection_name}]. Bắt đầu xóa...")
    
    # Xóa theo mẻ (tối đa 500 doc mỗi mẻ theo limit của Firestore batch)
    total_deleted = 0
    for i in range(0, len(docs_to_delete), BATCH_SIZE):
        batch = db.batch()
        batch_refs = docs_to_delete[i:i + BATCH_SIZE]
        for ref in batch_refs:
            batch.delete(ref)
        batch.commit()
        total_deleted += len(batch_refs)
        print(f"   -> Đã xóa {total_deleted}/{len(docs_to_delete)}...")
        time.sleep(1)
        
    print(f"🎉 Hoàn tất dọn dẹp [{collection_name}]! Đã xóa {total_deleted} bản ghi.")

if __name__ == "__main__":
    print("=== BẮT ĐẦU CHƯƠNG TRÌNH DỌN RÁC ===")
    
    # 1. Dọn dẹp đơn hàng (chỉ xóa đơn đã xong hoặc lỗi sau 7 ngày)
    delete_old_docs('orders', 3, status_field='status', status_values=['completed', 'failed'])
    
    # 2. Dọn dẹp lịch sử nạp coin (topups)
    # Xóa đơn pending cũ hơn 1 ngày
    delete_old_docs('topups', 1, status_field='status', status_values=['pending'])
    # Xóa đơn đã duyệt/lỗi cũ hơn 7 ngày
    delete_old_docs('topups', 7, status_field='status', status_values=['approved', 'rejected', 'failed'])
    
    # 3. Dọn dẹp Users (Người dùng cũ hơn 2 ngày VÀ không còn coin)
    delete_old_docs('users', 2, require_zero_coins=True)
    
    print("\n✅ TẤT CẢ QUÁ TRÌNH DỌN DẸP ĐÃ HOÀN TẤT!")
