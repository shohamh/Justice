from app.services.hr.schemas import (
    HrGroup,
    HrGroupWithReports,
    HrHealthCheckResult,
    HrUser,
    HrUserWithReports,
)


def test_hr_user_parses_full_payload():
    payload = {
        "username": "jdoe",
        "firstName": "John",
        "lastName": "Doe",
        "fullName": "John Doe",
        "imageUrl": "https://hr.example/img/1",
        "mail": "jdoe@example.mil",
        "status": "active",
        "nationalIdentifier": "123456789",
        "personalNumber": "7654321",
        "rank": "רב טוראי",
        "gender": "male",
        "servicType": "chova",
        "job": "operator",
        "profession": "logistics",
        "professionId": "42",
        "serviceStartDate": "2024-01-01",
        "serviceEndDate": None,
        "baseEntryDate": "2024-01-05",
        "t_personID": "abc-123",
        "address": "Tel Aviv",
        "jobStartDate": "2024-02-01",
        "endHovaDate": "2026-01-01",
        "dateOfBirth": "2002-03-04",
        "phone": "050-1234567",
        "voip": "1234",
        "manager": "jsmith",
        "managerName": "Jane Smith",
        "managerUserName": "jsmith",
        "managerPersonalNumber": "1112223",
        "organization": "Unit 8200",
        "hulia": "A",
        "huliaId": "h1",
        "huliaManager": "jsmith",
        "team": "Team 1",
        "teamId": "t1",
        "teamManager": "jsmith",
        "mador": "Mador 1",
        "madorId": "m1",
        "madorManager": "jsmith",
        "branch": "Branch 1",
        "branchId": "b1",
        "branchManager": "jsmith",
        "shetach": "Shetach 1",
        "shetachId": "s1",
        "shetachManager": "jsmith",
        "department": "Dept 1",
        "departmentId": "d1",
        "departmentManager": "jsmith",
        "palga": "Palga 1",
        "palgaManager": "jsmith",
        "unit": "Unit 1",
        "unitId": "u1",
        "unitManager": "jsmith",
        "maritalStatus": "single",
        "minuy": "regular",
        "minuyRank": "רב טוראי",
        "isRashatz": False,
        "isRamad": False,
        "isRaan": False,
        "isMafmar": False,
        "isMefakedYechida": False,
    }
    user = HrUser.model_validate(payload)
    assert user.personal_number == "7654321"
    assert user.full_name == "John Doe"
    assert user.image_url == "https://hr.example/img/1"
    assert user.service_start_date == "2024-01-01"
    assert user.is_rashatz is False


def test_hr_user_tolerates_missing_optional_fields():
    user = HrUser.model_validate({"personalNumber": "1", "fullName": "Only Required"})
    assert user.personal_number == "1"
    assert user.mail is None
    assert user.rank is None


def test_hr_user_image_url_raw_buffer_becomes_none():
    # Confirmed against real HR API responses: some users' imageUrl comes
    # back as a raw byte-buffer object instead of a URL string.
    user = HrUser.model_validate({
        "personalNumber": "1", "fullName": "Buffer User",
        "imageUrl": {"type": "Buffer", "data": [1, 2, 3]},
    })
    assert user.image_url is None


def test_hr_user_image_url_string_passes_through():
    user = HrUser.model_validate({
        "personalNumber": "1", "fullName": "URL User",
        "imageUrl": "https://hr.example/img/1",
    })
    assert user.image_url == "https://hr.example/img/1"


def test_hr_user_with_reports_parses_manages_list():
    payload = {
        "personalNumber": "1",
        "fullName": "Manager",
        "manages": [
            {"personalNumber": "2", "fullName": "Report One"},
            {"personalNumber": "3", "fullName": "Report Two"},
        ],
    }
    result = HrUserWithReports.model_validate(payload)
    assert len(result.manages) == 2
    assert result.manages[0].personal_number == "2"


def test_hr_user_with_reports_empty_manages():
    result = HrUserWithReports.model_validate({"personalNumber": "1", "fullName": "Solo", "manages": []})
    assert result.manages == []


def test_hr_group_parses_full_payload():
    payload = {
        "id": "g1",
        "name": "Group One",
        "kind": "unit",
        "unit": "Unit 1",
        "parentKind": "branch",
        "parentId": "b1",
        "parentName": "Branch 1",
    }
    group = HrGroup.model_validate(payload)
    assert group.id == "g1"
    assert group.parent_id == "b1"


def test_hr_group_with_reports_parses_subhierarchy():
    payload = {
        "id": "g1",
        "name": "Group One",
        "kind": "unit",
        "unit": "Unit 1",
        "parentKind": None,
        "parentId": None,
        "parentName": None,
        "subGroups": [{"id": "g2", "name": "Group Two", "kind": "team", "unit": "Unit 1",
                       "parentKind": "unit", "parentId": "g1", "parentName": "Group One"}],
    }
    result = HrGroupWithReports.model_validate(payload)
    assert len(result.sub_groups) == 1
    assert result.sub_groups[0].id == "g2"


def test_hr_health_check_result():
    ok = HrHealthCheckResult(ok=True, latency_ms=12.5, error=None)
    assert ok.ok is True
    failed = HrHealthCheckResult(ok=False, latency_ms=0.0, error="timeout")
    assert failed.error == "timeout"
