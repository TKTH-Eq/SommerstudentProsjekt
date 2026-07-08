#Test av EngineeringObject-klassen

from src.models.engineering_object import EngineeringObject


obj = EngineeringObject(
    id="DRI001",
    type="drilling_symbol",
    name="SHALE SHAKER",
    source_file="test.pdf",
    page=1
)

print(obj)