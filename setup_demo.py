import os
from pathlib import Path

def create_demo():
    # Definicja struktury projektów i zawartości notatek
    demo_data = {
        "Project_Alpha_ETL": """# Pipeline Optymalizacji ETL
- [x] Konfiguracja środowiska dev
- [ ] Implementacja logiki transformacji w Sparku
- [ ] Testy jednostkowe dla modułu walidacji danych
- [ ] #blocked Czekamy na dostęp do produkcyjnego bucketu S3 od zespołu SecOps
- [ ] Optymalizacja zużycia zasobów na klastrze EMR
- [ ] Przygotowanie dokumentacji dla operacji""",

        "Project_Beta_Migration": """# Migracja do Cloud 2.0
- [ ] Migracja schematów bazodanowych
- [ ] #blocked Zespół Sieciowy nie otworzył portów dla VPN
- [ ] Weryfikacja spójności danych po migracji
- [ ] Spotkanie z PO w sprawie priorytetów migracji
- [ ] Backup starych instancji on-premisowych
- [ ] Testy wydajnościowe nowego klastra Kafka
- [ ] Konfiguracja monitoringu i alertingu w Datadog
- [ ] #blocked Brak decyzji Architekta w sprawie szyfrowania danych w spoczynku
- [ ] Przygotowanie planu rollbacku
- [ ] Dokumentacja procedury CI/CD""",

        "Project_Gamma_Governance": """# Wdrożenie Data Governance
- [x] Inwentaryzacja źródeł danych
- [ ] Implementacja tagowania PII w katalogu danych
- [ ] Ustalenie właścicieli biznesowych dla tabel sprzedażowych
- [ ] Definicja polityki retencji danych""",

        "_Archive_2025": """# Stary projekt
- [x] Zrobione i zapomniane.""",
        
        "Project_Delta_Reporting": """# Nowy Dashboard Finansowy
- [ ] Zbieranie wymagań od stakeholderów
- [ ] Definicja kluczowych KPI
- [ ] #blocked Dane finansowe za Q1 nie są jeszcze gotowe w hurtowni (czekamy na zespół FinData)"""
    }

    print("🏗️ Tworzę demo dla Technical Project Managera...")

    projects_dir = Path("projects")
    projects_dir.mkdir(exist_ok=True)

    for proj_name, content in demo_data.items():
        proj_path = projects_dir / proj_name
        proj_path.mkdir(exist_ok=True)
        
        note_file = proj_path / "notes.md"
        note_file.write_text(content, encoding='utf-8')
        print(f"✅ Utworzono projekt: {proj_name}")

    print("\n🚀 Demo gotowe! Możesz teraz uruchomić: python agent_tpm_pro.py")

if __name__ == "__main__":
    create_demo()