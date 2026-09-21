import os
import shutil
import time

# 测试目录
TEST_DIR = r"E:\agent_test\file_manager_test"
SOURCE_FILE = r"E:\agent_test\excel_result.xlsx"

def log_step(num, action, start):
    elapsed = time.time() - start
    print(f"[Step {num:2d}] {action:<35} {elapsed:.2f}s", flush=True)
    return elapsed

def main():
    total_start = time.time()
    step_durations = []
    
    print("=" * 60, flush=True)
    print("文件管理器 E2E Test", flush=True)
    print("=" * 60, flush=True)
    
    try:
        # Step 1: 打开资源管理器 (创建测试目录)
        t = time.time()
        os.makedirs(TEST_DIR, exist_ok=True)
        dur = log_step(1, "打开资源管理器 (创建目录)", t)
        step_durations.append(dur)
        
        # Step 2: 新建文件夹
        t = time.time()
        new_folder = os.path.join(TEST_DIR, "NewFolder")
        os.makedirs(new_folder, exist_ok=True)
        dur = log_step(2, "新建文件夹 NewFolder", t)
        step_durations.append(dur)
        
        # Step 3: 复制文件
        t = time.time()
        dest_file = os.path.join(new_folder, "excel_result.xlsx")
        shutil.copy2(SOURCE_FILE, dest_file)
        dur = log_step(3, "复制文件到 NewFolder", t)
        step_durations.append(dur)
        
        # Step 4: 重命名
        t = time.time()
        renamed_file = os.path.join(new_folder, "renamed_file.xlsx")
        os.rename(dest_file, renamed_file)
        dur = log_step(4, "重命名文件", t)
        step_durations.append(dur)
        
        # Step 5: 删除
        t = time.time()
        os.remove(renamed_file)
        dur = log_step(5, "删除文件", t)
        step_durations.append(dur)
        
        # Step 6: 删除文件夹
        t = time.time()
        os.rmdir(new_folder)
        dur = log_step(6, "删除文件夹", t)
        step_durations.append(dur)
        
        # Step 7: 验证删除
        t = time.time()
        folder_exists = os.path.exists(new_folder)
        file_exists = os.path.exists(renamed_file)
        dur = log_step(7, f"验证: 文件夹={folder_exists}, 文件={file_exists}", t)
        step_durations.append(dur)
        
        # 清理测试目录
        os.rmdir(TEST_DIR)
        
        total_time = time.time() - total_start
        
        print("\n" + "=" * 60, flush=True)
        print("每步耗时汇总", flush=True)
        print("=" * 60, flush=True)
        for i, d in enumerate(step_durations, 1):
            print(f"  Step {i:2d}: {d:.2f}s", flush=True)
        print("-" * 60, flush=True)
        print(f"  总耗时: {total_time:.2f}s", flush=True)
        
        passed = not folder_exists and not file_exists and total_time < 30
        print(f"\n{'✓ TEST PASSED' if passed else '✗ TEST FAILED'}", flush=True)
        return passed
        
    except Exception as e:
        print(f"\n✗ ERROR: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
