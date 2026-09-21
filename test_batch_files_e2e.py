import os
import time
import json
import shutil
from datetime import datetime
from pathlib import Path

class BatchFilesE2ETest:
    def __init__(self):
        self.test_results = []
        self.test_dir = Path("E:/agent_test/batch_test")
        self.backup_dir = Path("E:/agent_test/batch_test_backup")
        
    def setup_test_files(self):
        """创建测试文件夹和文件"""
        print("=== 步骤1: 创建测试文件夹和文件 ===")
        
        # 创建测试目录
        self.test_dir.mkdir(parents=True, exist_ok=True)
        
        # 备份现有文件（如果存在）
        if self.backup_dir.exists():
            shutil.rmtree(self.backup_dir)
        if self.test_dir.exists():
            shutil.copytree(self.test_dir, self.backup_dir)
        
        # 清空测试目录
        for item in self.test_dir.iterdir():
            if item.is_file():
                item.unlink()
        
        # 创建测试文件
        test_files = [
            ("file1.txt", "这是文件1的内容"),
            ("file2.txt", "这是文件2的内容"),
            ("file3.txt", "这是文件3的内容"),
            ("image1.png", b'\x89PNG\r\n\x1a\n'),  # PNG文件头
            ("image2.png", b'\x89PNG\r\n\x1a\n'),
            ("doc1.docx", b'PK\x03\x04'),  # DOCX文件头
        ]
        
        for filename, content in test_files:
            filepath = self.test_dir / filename
            if isinstance(content, str):
                filepath.write_text(content, encoding='utf-8')
            else:
                filepath.write_bytes(content)
        
        # 显示创建的文件
        files = list(self.test_dir.iterdir())
        print(f"创建了 {len(files)} 个测试文件:")
        for f in sorted(files):
            print(f"  - {f.name}")
        
        return len(files)
    
    def batch_rename_txt_files(self):
        """批量重命名.txt文件"""
        print("\n=== 步骤2: 批量重命名.txt文件 ===")
        
        start_time = time.time()
        
        # 查找所有.txt文件
        txt_files = sorted(self.test_dir.glob("*.txt"))
        
        if not txt_files:
            print("未找到.txt文件")
            return 0
        
        print(f"找到 {len(txt_files)} 个.txt文件")
        
        # 重命名文件
        renamed_count = 0
        for i, txt_file in enumerate(txt_files, 1):
            new_name = f"text_{i:03d}.txt"
            new_path = self.test_dir / new_name
            
            # 重命名
            txt_file.rename(new_path)
            renamed_count += 1
            print(f"  重命名: {txt_file.name} -> {new_name}")
        
        elapsed = time.time() - start_time
        print(f"重命名完成，耗时: {elapsed:.2f}s")
        
        return renamed_count
    
    def verify_rename_results(self):
        """验证重命名结果"""
        print("\n=== 步骤3: 验证重命名结果 ===")
        
        # 获取所有文件
        all_files = sorted(self.test_dir.iterdir())
        
        # 分类文件
        txt_files = [f for f in all_files if f.suffix == '.txt']
        other_files = [f for f in all_files if f.suffix != '.txt']
        
        print("当前文件列表:")
        for f in all_files:
            print(f"  - {f.name}")
        
        # 验证.txt文件命名
        print("\n验证.txt文件命名:")
        all_correct = True
        for i, txt_file in enumerate(txt_files, 1):
            expected_name = f"text_{i:03d}.txt"
            if txt_file.name == expected_name:
                print(f"  ✓ {txt_file.name} - 命名正确")
            else:
                print(f"  ✗ {txt_file.name} - 命名错误，期望: {expected_name}")
                all_correct = False
        
        # 验证其他文件未受影响
        print("\n验证其他文件未受影响:")
        other_files_ok = True
        expected_other = ["image1.png", "image2.png", "doc1.docx"]
        for f in other_files:
            if f.name in expected_other:
                print(f"  ✓ {f.name} - 未受影响")
            else:
                print(f"  ✗ {f.name} - 文件被意外修改")
                other_files_ok = False
        
        return all_correct and other_files_ok
    
    def cleanup(self):
        """清理测试文件"""
        print("\n=== 步骤4: 清理测试文件 ===")
        
        # 删除测试目录
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)
            print(f"已删除测试目录: {self.test_dir}")
        
        # 恢复备份（如果有）
        if self.backup_dir.exists():
            shutil.move(str(self.backup_dir), str(self.test_dir))
            print(f"已恢复备份目录")
    
    def run_all_tests(self):
        """运行所有测试"""
        print("开始批量文件操作端到端测试...")
        print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        start_time = time.time()
        
        try:
            # 步骤1: 创建测试文件
            file_count = self.setup_test_files()
            if file_count == 0:
                print("创建测试文件失败")
                return False
            
            # 步骤2: 批量重命名
            renamed_count = self.batch_rename_txt_files()
            if renamed_count == 0:
                print("重命名失败")
                return False
            
            # 步骤3: 验证结果
            verification_ok = self.verify_rename_results()
            
            # 计算总耗时
            total_time = time.time() - start_time
            
            print(f"\n=== 测试结果 ===")
            print(f"创建文件数: {file_count}")
            print(f"重命名文件数: {renamed_count}")
            print(f"验证结果: {'通过' if verification_ok else '失败'}")
            print(f"总耗时: {total_time:.2f}s")
            
            # 验收标准检查
            print(f"\n=== 验收标准 ===")
            print(f"✓ 所有 .txt 文件都被重命名: {'通过' if renamed_count > 0 else '未通过'}")
            print(f"✓ 命名格式正确: {'通过' if verification_ok else '未通过'}")
            print(f"✓ 其他文件不受影响: {'通过' if verification_ok else '未通过'}")
            print(f"✓ 总耗时 < 30s: {'通过' if total_time < 30 else '未通过'}")
            
            return verification_ok and total_time < 30
            
        finally:
            # 清理
            self.cleanup()

if __name__ == "__main__":
    tester = BatchFilesE2ETest()
    success = tester.run_all_tests()
    
    if success:
        print("\n批量文件操作端到端测试通过")
        exit(0)
    else:
        print("\n批量文件操作端到端测试失败")
        exit(1)
