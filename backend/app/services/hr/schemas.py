from pydantic import BaseModel, ConfigDict, Field


class HrUser(BaseModel):
    """Raw HR API user record. Field names mirror the HR API's JSON keys via
    aliases; snake_case attribute names are Justice-side convenience only —
    no value mapping happens here (see subsystem 2 for that)."""

    model_config = ConfigDict(populate_by_name=True)

    username: str | None = None
    first_name: str | None = Field(default=None, alias="firstName")
    last_name: str | None = Field(default=None, alias="lastName")
    full_name: str = Field(alias="fullName")
    image_url: str | None = Field(default=None, alias="imageUrl")
    mail: str | None = None
    status: str | None = None
    national_identifier: str | None = Field(default=None, alias="nationalIdentifier")
    personal_number: str = Field(alias="personalNumber")
    rank: str | None = None
    gender: str | None = None
    serv_type: str | None = Field(default=None, alias="servicType")
    job: str | None = None
    profession: str | None = None
    profession_id: str | None = Field(default=None, alias="professionId")
    service_start_date: str | None = Field(default=None, alias="serviceStartDate")
    service_end_date: str | None = Field(default=None, alias="serviceEndDate")
    base_entry_date: str | None = Field(default=None, alias="baseEntryDate")
    t_person_id: str | None = Field(default=None, alias="t_personID")
    address: str | None = None
    job_start_date: str | None = Field(default=None, alias="jobStartDate")
    end_hova_date: str | None = Field(default=None, alias="endHovaDate")
    date_of_birth: str | None = Field(default=None, alias="dateOfBirth")
    phone: str | None = None
    voip: str | None = None
    manager: str | None = None
    manager_name: str | None = Field(default=None, alias="managerName")
    manager_user_name: str | None = Field(default=None, alias="managerUserName")
    manager_personal_number: str | None = Field(default=None, alias="managerPersonalNumber")
    organization: str | None = None
    hulia: str | None = None
    hulia_id: str | None = Field(default=None, alias="huliaId")
    hulia_manager: str | None = Field(default=None, alias="huliaManager")
    team: str | None = None
    team_id: str | None = Field(default=None, alias="teamId")
    team_manager: str | None = Field(default=None, alias="teamManager")
    mador: str | None = None
    mador_id: str | None = Field(default=None, alias="madorId")
    mador_manager: str | None = Field(default=None, alias="madorManager")
    branch: str | None = None
    branch_id: str | None = Field(default=None, alias="branchId")
    branch_manager: str | None = Field(default=None, alias="branchManager")
    shetach: str | None = None
    shetach_id: str | None = Field(default=None, alias="shetachId")
    shetach_manager: str | None = Field(default=None, alias="shetachManager")
    department: str | None = None
    department_id: str | None = Field(default=None, alias="departmentId")
    department_manager: str | None = Field(default=None, alias="departmentManager")
    palga: str | None = None
    palga_manager: str | None = Field(default=None, alias="palgaManager")
    unit: str | None = None
    unit_id: str | None = Field(default=None, alias="unitId")
    unit_manager: str | None = Field(default=None, alias="unitManager")
    marital_status: str | None = Field(default=None, alias="maritalStatus")
    minuy: str | None = None
    minuy_rank: str | None = Field(default=None, alias="minuyRank")
    is_rashatz: bool | None = Field(default=None, alias="isRashatz")
    is_ramad: bool | None = Field(default=None, alias="isRamad")
    is_raan: bool | None = Field(default=None, alias="isRaan")
    is_mafmar: bool | None = Field(default=None, alias="isMafmar")
    is_mefaked_yechida: bool | None = Field(default=None, alias="isMefakedYechida")


class HrUserWithReports(HrUser):
    """HR user extended with direct + indirect reports, as returned by the
    /subhierarchy endpoint."""

    manages: list[HrUser] = Field(default_factory=list)


class HrGroup(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    kind: str | None = None
    unit: str | None = None
    parent_kind: str | None = Field(default=None, alias="parentKind")
    parent_id: str | None = Field(default=None, alias="parentId")
    parent_name: str | None = Field(default=None, alias="parentName")


class HrGroupWithReports(HrGroup):
    """HR group extended with its subhierarchy. The HR API spec does not
    detail the exact nesting shape beyond "subhierarchy"; kept intentionally
    shallow (one level of sub_groups) rather than guessing a deep recursive
    shape — revisit if real fixture data shows otherwise."""

    # TODO: "subGroups" key name unconfirmed against real HR API responses — spec doesn't detail group subhierarchy shape beyond "+ manages" for users.
    sub_groups: list[HrGroup] = Field(default_factory=list, alias="subGroups")


class HrHealthCheckResult(BaseModel):
    ok: bool
    latency_ms: float
    error: str | None = None
