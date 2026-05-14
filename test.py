# PythonでCSVを読み込むコードを書いて
import csv  
with open('data.csv', 'r') as file:
    reader = csv.reader(file)
    for row in reader:
        print(row)
            
#  