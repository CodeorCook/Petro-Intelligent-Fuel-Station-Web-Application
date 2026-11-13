-- MANUAL IMPORT ONLY into a NEW EMPTY personal DB_TRAMXANG.
-- Never invoked by init-dev. No business data, passwords, roles or migrations
-- against an existing database. The transaction guard refuses existing tables.
BEGIN;
DO $$ BEGIN
 IF current_database() <> 'DB_TRAMXANG' OR EXISTS (SELECT 1 FROM pg_tables WHERE schemaname='public') OR
    EXISTS (SELECT 1 FROM pg_namespace WHERE nspname NOT IN ('public','information_schema') AND left(nspname,3)<>'pg_') THEN
   RAISE EXCEPTION 'Schema starter requires a NEW EMPTY local DB_TRAMXANG; existing data/schema must not be reset';
 END IF;
END $$;
--
-- PostgreSQL database dump
--


-- Dumped from database version 16.14
-- Dumped by pg_dump version 16.14

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

-- *not* creating schema, since initdb creates it


--
-- Name: SCHEMA public; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA public IS '';


--
-- Name: phase57_immutable_guard(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.phase57_immutable_guard() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF TG_TABLE_NAME = 'bien_dong_kho' THEN
    RAISE EXCEPTION 'Stock movements are append-only; audited correction required' USING ERRCODE='23514';
  ELSIF TG_TABLE_NAME = 'tru_bom' THEN
    IF TG_OP = 'DELETE' THEN
      IF OLD.tb_trangthai='PUMPING' OR OLD.tb_luyke>OLD.tb_mocdau THEN
        RAISE EXCEPTION 'Active or used pump cannot be deleted' USING ERRCODE='23514';
      END IF;
      RETURN OLD;
    END IF;
    IF (NEW.tb_ma,NEW.tx_ma,NEW.tb_mocdau,NEW.tb_nguon_sha256)
       IS DISTINCT FROM (OLD.tb_ma,OLD.tx_ma,OLD.tb_mocdau,OLD.tb_nguon_sha256) THEN
      RAISE EXCEPTION 'Pump identity and baseline are immutable' USING ERRCODE='23514';
    END IF;
    IF NEW.tb_luyke < OLD.tb_luyke THEN
      RAISE EXCEPTION 'Pump totalizer cannot decrease' USING ERRCODE='23514';
    END IF;
  ELSIF TG_TABLE_NAME = 'bon_chua' THEN
    IF TG_OP = 'DELETE' THEN
      IF OLD.bc_ton<>0 OR OLD.bc_giucho<>0 THEN
        RAISE EXCEPTION 'Stocked or reserved tank cannot be deleted' USING ERRCODE='23514';
      END IF;
      RETURN OLD;
    END IF;
    IF (NEW.bc_ma,NEW.tx_ma) IS DISTINCT FROM (OLD.bc_ma,OLD.tx_ma) THEN
      RAISE EXCEPTION 'Tank identity and station are immutable' USING ERRCODE='23514';
    END IF;
    IF NEW.nl_ma IS DISTINCT FROM OLD.nl_ma AND (OLD.bc_ton<>0 OR OLD.bc_giucho<>0
       OR EXISTS(SELECT 1 FROM public.bien_dong_kho WHERE bc_ma=OLD.bc_ma)
       OR EXISTS(SELECT 1 FROM public.giu_cho_nhien_lieu WHERE bc_ma=OLD.bc_ma)) THEN
      RAISE EXCEPTION 'Stocked or historical tank cannot change fuel' USING ERRCODE='23514';
    END IF;
  ELSIF TG_TABLE_NAME = 'giu_cho_nhien_lieu' THEN
    IF TG_OP = 'DELETE' THEN
      RAISE EXCEPTION 'Release reservations; do not erase history' USING ERRCODE='23514';
    END IF;
    IF OLD.gc_trangthai <> 'GIU_CHO' THEN
      RAISE EXCEPTION 'Terminal reservation is immutable' USING ERRCODE='23514';
    END IF;
    IF (NEW.yc_ma,NEW.nl_ma,NEW.bc_ma,NEW.tx_ma,NEW.gc_chedo,NEW.gia_ngaygio,NEW.gc_dongia,NEW.nd_tendangnhap,NEW.gc_ngaytao)
       IS DISTINCT FROM (OLD.yc_ma,OLD.nl_ma,OLD.bc_ma,OLD.tx_ma,OLD.gc_chedo,OLD.gia_ngaygio,OLD.gc_dongia,OLD.nd_tendangnhap,OLD.gc_ngaytao) THEN
      RAISE EXCEPTION 'Reservation identity and quoted price are immutable' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END $$;


--
-- Name: phase57_scope_guard(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.phase57_scope_guard() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE request_station CHAR(8); sale_request CHAR(8); sale_station CHAR(8);
BEGIN
  IF TG_TABLE_NAME = 'tru_bom' THEN
    IF NEW.yc_dang_bom IS NOT NULL THEN
      SELECT tx_ma INTO request_station FROM public.yeu_cau_do_xang WHERE yc_ma=NEW.yc_dang_bom;
      IF request_station IS DISTINCT FROM NEW.tx_ma THEN
        RAISE EXCEPTION 'Pump request is outside station scope' USING ERRCODE='23514';
      END IF;
    END IF;
  ELSE
    IF NEW.yc_ma IS NOT NULL THEN
      SELECT tx_ma INTO request_station FROM public.yeu_cau_do_xang WHERE yc_ma=NEW.yc_ma;
      IF request_station IS DISTINCT FROM NEW.tx_ma THEN
        RAISE EXCEPTION 'Operational request is outside station scope' USING ERRCODE='23514';
      END IF;
    END IF;
    IF TG_TABLE_NAME = 'bien_dong_kho' THEN
      IF NEW.gd_ma IS NOT NULL THEN
        SELECT g.yc_ma, coalesce(g.tx_ma,r.tx_ma) INTO sale_request,sale_station
          FROM public.giao_dich g JOIN public.yeu_cau_do_xang r ON r.yc_ma=g.yc_ma
          WHERE g.gd_ma=NEW.gd_ma;
        IF sale_request IS DISTINCT FROM NEW.yc_ma OR sale_station IS DISTINCT FROM NEW.tx_ma THEN
          RAISE EXCEPTION 'Stock movement does not match its sale/request' USING ERRCODE='23514';
        END IF;
      END IF;
    END IF;
  END IF;
  RETURN NEW;
END $$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: bien_dong_kho; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bien_dong_kho (
    bd_ma character(12) NOT NULL,
    bd_khoa_chonglap character varying(128) NOT NULL,
    bc_ma character varying(32) NOT NULL,
    tx_ma character(8) NOT NULL,
    nl_ma character(8) NOT NULL,
    bd_loai character varying(20) NOT NULL,
    bd_solit numeric(14,2) NOT NULL,
    bd_truoc numeric(14,2) NOT NULL,
    bd_sau numeric(14,2) NOT NULL,
    yc_ma character(8),
    gd_ma character(8),
    tb_ma character varying(32),
    bd_luyke_truoc numeric(18,2),
    bd_luyke_sau numeric(18,2),
    bd_lydo_khong_tru character varying(256),
    bd_nhacungcap character varying(256),
    nd_tendangnhap character varying(32) NOT NULL,
    bd_nguon_sha256 character(64),
    bd_nguon_key character varying(128),
    bd_ngaytao timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT ck_bd_arithmetic CHECK (((((bd_loai)::text = 'XUAT'::text) AND (bd_sau = (bd_truoc - bd_solit))) OR (((bd_loai)::text <> 'XUAT'::text) AND (bd_sau = (bd_truoc + bd_solit))))),
    CONSTRAINT ck_bd_balance CHECK (((bd_truoc <> 'NaN'::numeric) AND (bd_truoc >= (0)::numeric) AND (bd_sau <> 'NaN'::numeric) AND (bd_sau >= (0)::numeric))),
    CONSTRAINT ck_bd_key CHECK ((length(btrim((bd_khoa_chonglap)::text)) > 0)),
    CONSTRAINT ck_bd_loai CHECK (((bd_loai)::text = ANY ((ARRAY['NHAP'::character varying, 'XUAT'::character varying, 'KHOI_TAO_DI_TRU'::character varying])::text[]))),
    CONSTRAINT ck_bd_migration_source CHECK (((((bd_loai)::text = 'KHOI_TAO_DI_TRU'::text) AND (bd_truoc = (0)::numeric) AND (bd_nguon_sha256 IS NOT NULL) AND (bd_nguon_key IS NOT NULL)) OR (((bd_loai)::text <> 'KHOI_TAO_DI_TRU'::text) AND (bd_nguon_sha256 IS NULL) AND (bd_nguon_key IS NULL)))),
    CONSTRAINT ck_bd_sale_refs CHECK (((((bd_loai)::text = 'XUAT'::text) AND (yc_ma IS NOT NULL) AND (gd_ma IS NOT NULL)) OR (((bd_loai)::text <> 'XUAT'::text) AND (yc_ma IS NULL) AND (gd_ma IS NULL) AND (tb_ma IS NULL)))),
    CONSTRAINT ck_bd_sha CHECK (((bd_nguon_sha256 IS NULL) OR (bd_nguon_sha256 ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT ck_bd_solit CHECK (((bd_solit <> 'NaN'::numeric) AND (bd_solit > (0)::numeric))),
    CONSTRAINT ck_bd_totalizer CHECK ((((tb_ma IS NULL) AND (bd_luyke_truoc IS NULL) AND (bd_luyke_sau IS NULL)) OR ((tb_ma IS NOT NULL) AND (bd_luyke_truoc IS NOT NULL) AND (bd_luyke_sau IS NOT NULL) AND (bd_luyke_truoc <> 'NaN'::numeric) AND (bd_luyke_truoc >= (0)::numeric) AND (bd_luyke_sau <> 'NaN'::numeric) AND (bd_luyke_sau = (bd_luyke_truoc + bd_solit))))),
    CONSTRAINT ck_bd_unassigned CHECK (((((bd_loai)::text = 'XUAT'::text) AND (tb_ma IS NULL) AND (length(btrim((COALESCE(bd_lydo_khong_tru, ''::character varying))::text)) > 0)) OR ((((bd_loai)::text <> 'XUAT'::text) OR (tb_ma IS NOT NULL)) AND (bd_lydo_khong_tru IS NULL))))
);


--
-- Name: bon_chua; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bon_chua (
    bc_ma character varying(32) NOT NULL,
    tx_ma character(8) NOT NULL,
    nl_ma character(8) NOT NULL,
    bc_ten character varying(128) NOT NULL,
    bc_dungtich numeric(14,2) NOT NULL,
    bc_ton numeric(14,2) DEFAULT 0 NOT NULL,
    bc_giucho numeric(14,2) DEFAULT 0 NOT NULL,
    bc_nguong numeric(14,2) NOT NULL,
    bc_hoatdong boolean DEFAULT true NOT NULL,
    bc_phienban integer DEFAULT 0 NOT NULL,
    bc_ngaytao timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    bc_ngaycapnhat timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT ck_bc_dungtich CHECK (((bc_dungtich <> 'NaN'::numeric) AND (bc_dungtich > (0)::numeric))),
    CONSTRAINT ck_bc_giucho CHECK (((bc_giucho <> 'NaN'::numeric) AND (bc_giucho >= (0)::numeric) AND (bc_giucho <= bc_ton))),
    CONSTRAINT ck_bc_id CHECK (((bc_ma)::text ~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$'::text)),
    CONSTRAINT ck_bc_nguong CHECK (((bc_nguong <> 'NaN'::numeric) AND (bc_nguong >= (0)::numeric) AND (bc_nguong <= bc_dungtich))),
    CONSTRAINT ck_bc_phienban CHECK ((bc_phienban >= 0)),
    CONSTRAINT ck_bc_ten CHECK ((length(btrim((bc_ten)::text)) > 0)),
    CONSTRAINT ck_bc_ton CHECK (((bc_ton <> 'NaN'::numeric) AND (bc_ton >= (0)::numeric) AND (bc_ton <= bc_dungtich)))
);


--
-- Name: chi_tiet_giao_dich; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chi_tiet_giao_dich (
    nl_ma character(8) NOT NULL,
    gd_ma character(8) NOT NULL,
    soluong numeric(8,2) NOT NULL,
    thanhtien numeric(12,4) NOT NULL,
    dongialucban numeric(12,4) NOT NULL
);


--
-- Name: chitiet_yeucau; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chitiet_yeucau (
    yc_ma character(8) NOT NULL,
    nl_ma character(8) NOT NULL,
    soluong numeric(8,2),
    thanhtien numeric(12,4)
);


--
-- Name: danh_gia; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.danh_gia (
    dg_ma character(8) NOT NULL,
    nd_tendangnhap character varying(32) NOT NULL,
    tx_ma character(8) NOT NULL,
    ngaygio date NOT NULL,
    dg_noidung text NOT NULL,
    dg_mucdo smallint NOT NULL,
    gd_ma character(8),
    CONSTRAINT ck_transaction_review_content CHECK (((gd_ma IS NULL) OR (((dg_mucdo >= 1) AND (dg_mucdo <= 5)) AND (char_length(dg_noidung) <= 500))))
);


--
-- Name: dich_vu; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dich_vu (
    dv_ma character(8) NOT NULL,
    dv_ten character varying(64) NOT NULL
);


--
-- Name: doanh_nghiep; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.doanh_nghiep (
    nd_tendangnhap character varying(32) NOT NULL,
    dn_trangthai character varying(20) DEFAULT 'CHUA_HOAN_THIEN'::character varying NOT NULL,
    dn_du_lieu_cu boolean DEFAULT false NOT NULL,
    CONSTRAINT ck_doanh_nghiep_trangthai CHECK (((dn_trangthai)::text = ANY ((ARRAY['CHUA_HOAN_THIEN'::character varying, 'CHO_DUYET'::character varying, 'CAN_BO_SUNG'::character varying, 'TU_CHOI'::character varying, 'DA_DUYET'::character varying, 'TAM_KHOA'::character varying])::text[])))
);


--
-- Name: don_vi_tinh; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.don_vi_tinh (
    dvt_ma character(8) NOT NULL,
    dvt_ten character varying(20) NOT NULL
);


--
-- Name: gia; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.gia (
    ngaygio date NOT NULL,
    tx_ma character(8) NOT NULL,
    nl_ma character(8) NOT NULL,
    dongia numeric(12,4) NOT NULL
);


--
-- Name: gia_tham_chieu; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.gia_tham_chieu (
    id bigint NOT NULL,
    source character varying(16) NOT NULL,
    region character varying(8) NOT NULL,
    fuel_id character(8) NOT NULL,
    price numeric(12,0) NOT NULL,
    effective_date date NOT NULL,
    effective_time time without time zone,
    source_url text NOT NULL,
    synced_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_reference_fuel CHECK ((fuel_id = ANY (ARRAY['NL000001'::bpchar, 'NL000002'::bpchar, 'NL000003'::bpchar]))),
    CONSTRAINT ck_reference_source_region CHECK (((((source)::text = 'petrolimex'::text) AND ((region)::text = '2'::text)) OR (((source)::text = 'pvoil'::text) AND ((region)::text = 'national'::text)))),
    CONSTRAINT gia_tham_chieu_price_check CHECK (((price > (0)::numeric) AND (price < (1000000000)::numeric))),
    CONSTRAINT gia_tham_chieu_source_url_check CHECK (("left"(source_url, 8) = 'https://'::text))
);


--
-- Name: TABLE gia_tham_chieu; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.gia_tham_chieu IS 'PETRO_SCHEMA_35_REFERENCE_V1';


--
-- Name: gia_tham_chieu_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.gia_tham_chieu ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.gia_tham_chieu_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: giao_dich; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.giao_dich (
    gd_ma character(8) NOT NULL,
    nd_tendangnhap character varying(32) NOT NULL,
    tklk_mathe character varying(32),
    tt_ma character(8) NOT NULL,
    ngaygio date NOT NULL,
    yc_ma character(8) NOT NULL,
    gd_sotien numeric(12,4) NOT NULL,
    gd_mathamchieu character varying(64) NOT NULL,
    tx_ma character(8),
    pttt_ten character varying(32) DEFAULT 'VIETQR'::character varying
);


--
-- Name: giu_cho_nhien_lieu; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.giu_cho_nhien_lieu (
    yc_ma character(8) NOT NULL,
    nl_ma character(8) NOT NULL,
    bc_ma character varying(32) NOT NULL,
    tx_ma character(8) NOT NULL,
    gc_solit numeric(8,2) NOT NULL,
    gc_chedo character varying(32) NOT NULL,
    gia_ngaygio date NOT NULL,
    gc_dongia numeric(12,4) NOT NULL,
    gc_trangthai character varying(20) DEFAULT 'GIU_CHO'::character varying NOT NULL,
    nd_tendangnhap character varying(32) NOT NULL,
    gc_ngaytao timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    gc_ngaycapnhat timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT ck_gc_chedo CHECK (((gc_chedo)::text = ANY ((ARRAY['SO_LIT'::character varying, 'SO_TIEN'::character varying, 'DO_DAY_BINH'::character varying])::text[]))),
    CONSTRAINT ck_gc_dongia CHECK (((gc_dongia <> 'NaN'::numeric) AND (gc_dongia > (0)::numeric))),
    CONSTRAINT ck_gc_solit CHECK (((gc_solit <> 'NaN'::numeric) AND (gc_solit > (0)::numeric))),
    CONSTRAINT ck_gc_trangthai CHECK (((gc_trangthai)::text = ANY ((ARRAY['GIU_CHO'::character varying, 'DA_TIEU_THU'::character varying, 'DA_HUY'::character varying])::text[])))
);


--
-- Name: he_so_giao_thong; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.he_so_giao_thong (
    hsgt_ma character(8) NOT NULL,
    td_ma character(8) NOT NULL,
    gio_bat_dau time without time zone NOT NULL,
    gio_ket_thuc time without time zone NOT NULL,
    he_so numeric(4,2) NOT NULL,
    muc_do character varying(20) NOT NULL,
    CONSTRAINT ck_he_so_giao_thong_he_so CHECK ((he_so >= 1.0)),
    CONSTRAINT ck_he_so_giao_thong_khung_gio CHECK ((gio_bat_dau <= gio_ket_thuc)),
    CONSTRAINT ck_he_so_giao_thong_muc_do CHECK (((muc_do)::text = ANY ((ARRAY['THONG_THOANG'::character varying, 'XE_DONG'::character varying, 'UN_TAC_CUC_BO'::character varying, 'KET_CUNG'::character varying])::text[])))
);


--
-- Name: ho_so_doanh_nghiep; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ho_so_doanh_nghiep (
    hsdn_ma character(12) NOT NULL,
    nd_tendangnhap character varying(32) NOT NULL,
    hsdn_tenphaply character varying(128),
    hsdn_masothue character varying(20),
    hsdn_diachi character varying(256),
    hsdn_nguoidaidien character varying(128),
    hsdn_sodienthoai character varying(11),
    hsdn_email character varying(128),
    hsdn_ngaycapnhat timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: khach_hang; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.khach_hang (
    nd_tendangnhap character varying(32) NOT NULL
);


--
-- Name: loai_phuong_tien; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.loai_phuong_tien (
    lpt_ma character(8) NOT NULL,
    lpt_ten character varying(20) NOT NULL
);


--
-- Name: ngan_hang; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ngan_hang (
    nh_ma character(8) NOT NULL,
    nh_ten character varying(64) NOT NULL
);


--
-- Name: nguoi_dung; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.nguoi_dung (
    nd_tendangnhap character varying(32) NOT NULL,
    nd_matkhau character varying(256) NOT NULL,
    nd_cccd character(12),
    nd_ten character varying(32) NOT NULL,
    nd_sodienthoai character varying(11) NOT NULL,
    nd_email character varying(64) NOT NULL,
    nd_gioitinh boolean
);


--
-- Name: nhien_lieu; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.nhien_lieu (
    nl_ma character(8) NOT NULL,
    dvt_ma character(8) NOT NULL,
    nl_ten character varying(64) NOT NULL
);


--
-- Name: phuong_tien; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.phuong_tien (
    pt_bienso character(12) NOT NULL,
    lpt_ma character(8) NOT NULL,
    nd_tendangnhap character varying(32) NOT NULL,
    pt_ten character varying(32) NOT NULL
);


--
-- Name: quan_tri_vien; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.quan_tri_vien (
    nd_tendangnhap character varying(32) NOT NULL
);


--
-- Name: tai_khoan_lien_ket; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tai_khoan_lien_ket (
    tklk_mathe character varying(32) NOT NULL,
    nh_ma character(8) NOT NULL,
    nd_tendangnhap character varying(32) NOT NULL
);


--
-- Name: tep_minh_chung; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tep_minh_chung (
    tmc_ma character(12) NOT NULL,
    ycdn_ma character(12),
    ycdt_ma character(12),
    tmc_ten character varying(255) NOT NULL,
    tmc_duongdan character varying(512) NOT NULL,
    tmc_mime character varying(100),
    tmc_kich_thuoc bigint,
    tmc_sha256 character(64),
    tmc_ngaytai timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT ck_tmc_chi_mot_yeu_cau CHECK (((ycdn_ma IS NOT NULL) <> (ycdt_ma IS NOT NULL))),
    CONSTRAINT ck_tmc_kich_thuoc CHECK (((tmc_kich_thuoc IS NULL) OR (tmc_kich_thuoc >= 0)))
);


--
-- Name: thoi_diem; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.thoi_diem (
    ngaygio date NOT NULL
);


--
-- Name: tram_xang; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tram_xang (
    tx_ma character(8) NOT NULL,
    nd_tendangnhap character varying(32) NOT NULL,
    tx_ten character varying(64) NOT NULL,
    tx_diachi character varying(128) NOT NULL,
    tx_kinhdo numeric(11,8) NOT NULL,
    tx_vido numeric(10,8) NOT NULL,
    tx_coconluon boolean DEFAULT false,
    tx_trucduong character varying(64),
    tx_trangthai character varying(20) DEFAULT 'NHAP'::character varying NOT NULL,
    tx_congkhai boolean DEFAULT false NOT NULL,
    tx_du_lieu_cu boolean DEFAULT false NOT NULL,
    tx_phienban_hientai integer DEFAULT 0 NOT NULL,
    CONSTRAINT ck_tram_xang_congkhai CHECK (((tx_congkhai = false) OR ((tx_trangthai)::text = 'DA_DUYET'::text))),
    CONSTRAINT ck_tram_xang_phienban CHECK ((tx_phienban_hientai >= 0)),
    CONSTRAINT ck_tram_xang_trangthai CHECK (((tx_trangthai)::text = ANY ((ARRAY['NHAP'::character varying, 'CHO_DUYET'::character varying, 'CAN_BO_SUNG'::character varying, 'TU_CHOI'::character varying, 'DA_DUYET'::character varying, 'TAM_NGUNG'::character varying])::text[])))
);


--
-- Name: trang_thai; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trang_thai (
    tt_ma character(8) NOT NULL,
    tt_ten character varying(32) NOT NULL
);


--
-- Name: trang_thai_xac_nhan; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trang_thai_xac_nhan (
    ttxn_ma character(8) NOT NULL,
    ttxn_ten character varying(20) NOT NULL
);


--
-- Name: tru_bom; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tru_bom (
    tb_ma character varying(32) NOT NULL,
    tx_ma character(8) NOT NULL,
    tb_code character varying(32) NOT NULL,
    tb_ten character varying(128) NOT NULL,
    tb_trangthai character varying(20) DEFAULT 'OFFLINE'::character varying NOT NULL,
    tb_mocdau numeric(18,2) NOT NULL,
    tb_luyke numeric(18,2) NOT NULL,
    yc_dang_bom character(8),
    tb_nguon_sha256 character(64),
    tb_phienban integer DEFAULT 0 NOT NULL,
    tb_ngaytao timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    tb_ngaycapnhat timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT ck_tb_code CHECK (((tb_code)::text ~ '^[A-Z0-9][A-Z0-9_-]{0,31}$'::text)),
    CONSTRAINT ck_tb_id CHECK (((tb_ma)::text ~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$'::text)),
    CONSTRAINT ck_tb_luyke CHECK (((tb_luyke <> 'NaN'::numeric) AND (tb_luyke >= tb_mocdau))),
    CONSTRAINT ck_tb_mocdau CHECK (((tb_mocdau <> 'NaN'::numeric) AND (tb_mocdau >= (0)::numeric))),
    CONSTRAINT ck_tb_phienban CHECK ((tb_phienban >= 0)),
    CONSTRAINT ck_tb_session CHECK (((((tb_trangthai)::text = 'PUMPING'::text) AND (yc_dang_bom IS NOT NULL)) OR (((tb_trangthai)::text <> 'PUMPING'::text) AND (yc_dang_bom IS NULL)))),
    CONSTRAINT ck_tb_sha CHECK (((tb_nguon_sha256 IS NULL) OR (tb_nguon_sha256 ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT ck_tb_ten CHECK ((length(btrim((tb_ten)::text)) > 0)),
    CONSTRAINT ck_tb_trangthai CHECK (((tb_trangthai)::text = ANY ((ARRAY['READY'::character varying, 'OFFLINE'::character varying, 'MAINTENANCE'::character varying, 'PUMPING'::character varying])::text[])))
);


--
-- Name: tru_bom_nhien_lieu; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tru_bom_nhien_lieu (
    tb_ma character varying(32) NOT NULL,
    tx_ma character(8) NOT NULL,
    nl_ma character(8) NOT NULL
);


--
-- Name: tuyen_duong; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tuyen_duong (
    td_ma character(8) NOT NULL,
    td_ten character varying(100) NOT NULL,
    td_khu_vuc character varying(100)
);


--
-- Name: tx_dv; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tx_dv (
    dv_ma character(8) NOT NULL,
    tx_ma character(8) NOT NULL
);


--
-- Name: v_tram_xang_cong_khai; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_tram_xang_cong_khai AS
 SELECT tx.tx_ma,
    tx.nd_tendangnhap,
    tx.tx_ten,
    tx.tx_diachi,
    tx.tx_kinhdo,
    tx.tx_vido,
    tx.tx_coconluon,
    tx.tx_trucduong,
    tx.tx_trangthai,
    tx.tx_congkhai,
    tx.tx_du_lieu_cu,
    tx.tx_phienban_hientai
   FROM (public.tram_xang tx
     JOIN public.doanh_nghiep dn ON (((dn.nd_tendangnhap)::text = (tx.nd_tendangnhap)::text)))
  WHERE (((tx.tx_trangthai)::text = 'DA_DUYET'::text) AND (tx.tx_congkhai = true) AND ((dn.dn_trangthai)::text = 'DA_DUYET'::text));


--
-- Name: vi_tri_hien_tai; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vi_tri_hien_tai (
    nd_tendangnhap character varying(32) NOT NULL,
    thoigian timestamp without time zone NOT NULL,
    kinhdo numeric(11,8) NOT NULL,
    vido numeric(10,8) NOT NULL
);


--
-- Name: yeu_cau_do_xang; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.yeu_cau_do_xang (
    yc_ma character(8) NOT NULL,
    ttxn_ma character(8) NOT NULL,
    tx_ma character(8) NOT NULL,
    nd_tendangnhap character varying(32) NOT NULL,
    pt_bienso character(12),
    hinh_thuc_do_xang character varying(32),
    thoi_gian_tao timestamp without time zone,
    yc_het_han_luc timestamp with time zone,
    yc_dong_luc timestamp with time zone,
    yc_dong_boi character varying(32),
    yc_lydo_dong character varying(256),
    CONSTRAINT ck_yc_terminal_metadata CHECK (((ttxn_ma <> ALL (ARRAY['TTXN0006'::bpchar, 'TTXN0007'::bpchar])) OR ((yc_dong_luc IS NOT NULL) AND (length(btrim((yc_lydo_dong)::text)) > 0) AND (yc_lydo_dong IS NOT NULL))))
);


--
-- Name: yeu_cau_duyet_doanh_nghiep; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.yeu_cau_duyet_doanh_nghiep (
    ycdn_ma character(12) NOT NULL,
    hsdn_ma character(12) NOT NULL,
    ycdn_lan_gui integer NOT NULL,
    ycdn_dulieu jsonb NOT NULL,
    ycdn_trangthai character varying(20) DEFAULT 'CHO_DUYET'::character varying NOT NULL,
    ycdn_ngaygui timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    qtv_tendangnhap character varying(32),
    ycdn_ngayxuly timestamp with time zone,
    ycdn_lydo text,
    CONSTRAINT ck_ycdn_dulieu CHECK ((jsonb_typeof(ycdn_dulieu) = 'object'::text)),
    CONSTRAINT ck_ycdn_lan_gui CHECK ((ycdn_lan_gui >= 1)),
    CONSTRAINT ck_ycdn_trangthai CHECK (((ycdn_trangthai)::text = ANY ((ARRAY['CHO_DUYET'::character varying, 'CAN_BO_SUNG'::character varying, 'TU_CHOI'::character varying, 'DA_DUYET'::character varying])::text[]))),
    CONSTRAINT ck_ycdn_xuly CHECK (((((ycdn_trangthai)::text = 'CHO_DUYET'::text) AND (qtv_tendangnhap IS NULL) AND (ycdn_ngayxuly IS NULL)) OR (((ycdn_trangthai)::text <> 'CHO_DUYET'::text) AND (qtv_tendangnhap IS NOT NULL) AND (ycdn_ngayxuly IS NOT NULL))))
);


--
-- Name: yeu_cau_duyet_tram; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.yeu_cau_duyet_tram (
    ycdt_ma character(12) NOT NULL,
    tx_ma character(8) NOT NULL,
    ycdt_lan_gui integer NOT NULL,
    ycdt_loai character varying(20) NOT NULL,
    ycdt_dulieu jsonb NOT NULL,
    ycdt_trangthai character varying(20) DEFAULT 'CHO_DUYET'::character varying NOT NULL,
    ycdt_ngaygui timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    qtv_tendangnhap character varying(32),
    ycdt_ngayxuly timestamp with time zone,
    ycdt_lydo text,
    CONSTRAINT ck_ycdt_dulieu CHECK ((jsonb_typeof(ycdt_dulieu) = 'object'::text)),
    CONSTRAINT ck_ycdt_lan_gui CHECK ((ycdt_lan_gui >= 1)),
    CONSTRAINT ck_ycdt_loai CHECK (((ycdt_loai)::text = ANY ((ARRAY['DANG_KY_MOI'::character varying, 'CAP_NHAT'::character varying])::text[]))),
    CONSTRAINT ck_ycdt_trangthai CHECK (((ycdt_trangthai)::text = ANY ((ARRAY['CHO_DUYET'::character varying, 'CAN_BO_SUNG'::character varying, 'TU_CHOI'::character varying, 'DA_DUYET'::character varying])::text[]))),
    CONSTRAINT ck_ycdt_xuly CHECK (((((ycdt_trangthai)::text = 'CHO_DUYET'::text) AND (qtv_tendangnhap IS NULL) AND (ycdt_ngayxuly IS NULL)) OR (((ycdt_trangthai)::text <> 'CHO_DUYET'::text) AND (qtv_tendangnhap IS NOT NULL) AND (ycdt_ngayxuly IS NOT NULL)) OR (((ycdt_trangthai)::text = 'DA_DUYET'::text) AND (qtv_tendangnhap IS NULL) AND (ycdt_ngayxuly IS NOT NULL) AND (COALESCE((ycdt_dulieu ->> 'activation_method'::text), ''::text) = 'SELF_SERVICE_DEMO'::text) AND (COALESCE((ycdt_dulieu ->> 'activation_actor'::text), ''::text) <> ''::text) AND ((ycdt_dulieu ->> 'activation_actor'::text) = COALESCE((ycdt_dulieu ->> 'nd_tendangnhap'::text), ''::text)))))
);


--
-- Name: gia_tham_chieu gia_tham_chieu_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gia_tham_chieu
    ADD CONSTRAINT gia_tham_chieu_pkey PRIMARY KEY (id);


--
-- Name: he_so_giao_thong he_so_giao_thong_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.he_so_giao_thong
    ADD CONSTRAINT he_so_giao_thong_pkey PRIMARY KEY (hsgt_ma);


--
-- Name: bien_dong_kho pk_bien_dong_kho; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bien_dong_kho
    ADD CONSTRAINT pk_bien_dong_kho PRIMARY KEY (bd_ma);


--
-- Name: bon_chua pk_bon_chua; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bon_chua
    ADD CONSTRAINT pk_bon_chua PRIMARY KEY (bc_ma);


--
-- Name: chi_tiet_giao_dich pk_chi_tiet_giao_dich; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chi_tiet_giao_dich
    ADD CONSTRAINT pk_chi_tiet_giao_dich PRIMARY KEY (nl_ma, gd_ma);


--
-- Name: chitiet_yeucau pk_chitiet_yeucau; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chitiet_yeucau
    ADD CONSTRAINT pk_chitiet_yeucau PRIMARY KEY (yc_ma, nl_ma);


--
-- Name: danh_gia pk_danh_gia; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.danh_gia
    ADD CONSTRAINT pk_danh_gia PRIMARY KEY (dg_ma);


--
-- Name: dich_vu pk_dich_vu; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dich_vu
    ADD CONSTRAINT pk_dich_vu PRIMARY KEY (dv_ma);


--
-- Name: doanh_nghiep pk_doanh_nghiep; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.doanh_nghiep
    ADD CONSTRAINT pk_doanh_nghiep PRIMARY KEY (nd_tendangnhap);


--
-- Name: don_vi_tinh pk_don_vi_tinh; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.don_vi_tinh
    ADD CONSTRAINT pk_don_vi_tinh PRIMARY KEY (dvt_ma);


--
-- Name: gia pk_gia; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gia
    ADD CONSTRAINT pk_gia PRIMARY KEY (ngaygio, tx_ma, nl_ma);


--
-- Name: giao_dich pk_giao_dich; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.giao_dich
    ADD CONSTRAINT pk_giao_dich PRIMARY KEY (gd_ma);


--
-- Name: giu_cho_nhien_lieu pk_giu_cho_nhien_lieu; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.giu_cho_nhien_lieu
    ADD CONSTRAINT pk_giu_cho_nhien_lieu PRIMARY KEY (yc_ma, nl_ma, bc_ma);


--
-- Name: ho_so_doanh_nghiep pk_ho_so_doanh_nghiep; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ho_so_doanh_nghiep
    ADD CONSTRAINT pk_ho_so_doanh_nghiep PRIMARY KEY (hsdn_ma);


--
-- Name: khach_hang pk_khach_hang; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.khach_hang
    ADD CONSTRAINT pk_khach_hang PRIMARY KEY (nd_tendangnhap);


--
-- Name: loai_phuong_tien pk_loai_phuong_tien; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.loai_phuong_tien
    ADD CONSTRAINT pk_loai_phuong_tien PRIMARY KEY (lpt_ma);


--
-- Name: ngan_hang pk_ngan_hang; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ngan_hang
    ADD CONSTRAINT pk_ngan_hang PRIMARY KEY (nh_ma);


--
-- Name: nguoi_dung pk_nguoi_dung; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.nguoi_dung
    ADD CONSTRAINT pk_nguoi_dung PRIMARY KEY (nd_tendangnhap);


--
-- Name: nhien_lieu pk_nhien_lieu; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.nhien_lieu
    ADD CONSTRAINT pk_nhien_lieu PRIMARY KEY (nl_ma);


--
-- Name: phuong_tien pk_phuong_tien; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.phuong_tien
    ADD CONSTRAINT pk_phuong_tien PRIMARY KEY (pt_bienso);


--
-- Name: quan_tri_vien pk_quan_tri_vien; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quan_tri_vien
    ADD CONSTRAINT pk_quan_tri_vien PRIMARY KEY (nd_tendangnhap);


--
-- Name: tai_khoan_lien_ket pk_tai_khoan_lien_ket; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tai_khoan_lien_ket
    ADD CONSTRAINT pk_tai_khoan_lien_ket PRIMARY KEY (tklk_mathe);


--
-- Name: tep_minh_chung pk_tep_minh_chung; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tep_minh_chung
    ADD CONSTRAINT pk_tep_minh_chung PRIMARY KEY (tmc_ma);


--
-- Name: thoi_diem pk_thoi_diem; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.thoi_diem
    ADD CONSTRAINT pk_thoi_diem PRIMARY KEY (ngaygio);


--
-- Name: tram_xang pk_tram_xang; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tram_xang
    ADD CONSTRAINT pk_tram_xang PRIMARY KEY (tx_ma);


--
-- Name: trang_thai pk_trang_thai; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trang_thai
    ADD CONSTRAINT pk_trang_thai PRIMARY KEY (tt_ma);


--
-- Name: trang_thai_xac_nhan pk_trang_thai_xac_nhan; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trang_thai_xac_nhan
    ADD CONSTRAINT pk_trang_thai_xac_nhan PRIMARY KEY (ttxn_ma);


--
-- Name: tru_bom pk_tru_bom; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tru_bom
    ADD CONSTRAINT pk_tru_bom PRIMARY KEY (tb_ma);


--
-- Name: tru_bom_nhien_lieu pk_tru_bom_nhien_lieu; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tru_bom_nhien_lieu
    ADD CONSTRAINT pk_tru_bom_nhien_lieu PRIMARY KEY (tb_ma, nl_ma);


--
-- Name: tx_dv pk_tx_dv; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tx_dv
    ADD CONSTRAINT pk_tx_dv PRIMARY KEY (dv_ma, tx_ma);


--
-- Name: vi_tri_hien_tai pk_vi_tri_hien_tai; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vi_tri_hien_tai
    ADD CONSTRAINT pk_vi_tri_hien_tai PRIMARY KEY (nd_tendangnhap, thoigian);


--
-- Name: yeu_cau_do_xang pk_yeu_cau_do_xang; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.yeu_cau_do_xang
    ADD CONSTRAINT pk_yeu_cau_do_xang PRIMARY KEY (yc_ma);


--
-- Name: yeu_cau_duyet_doanh_nghiep pk_yeu_cau_duyet_doanh_nghiep; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.yeu_cau_duyet_doanh_nghiep
    ADD CONSTRAINT pk_yeu_cau_duyet_doanh_nghiep PRIMARY KEY (ycdn_ma);


--
-- Name: yeu_cau_duyet_tram pk_yeu_cau_duyet_tram; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.yeu_cau_duyet_tram
    ADD CONSTRAINT pk_yeu_cau_duyet_tram PRIMARY KEY (ycdt_ma);


--
-- Name: tuyen_duong tuyen_duong_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tuyen_duong
    ADD CONSTRAINT tuyen_duong_pkey PRIMARY KEY (td_ma);


--
-- Name: bon_chua uq_bc_station_fuel; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bon_chua
    ADD CONSTRAINT uq_bc_station_fuel UNIQUE (bc_ma, tx_ma, nl_ma);


--
-- Name: bien_dong_kho uq_bd_idempotency; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bien_dong_kho
    ADD CONSTRAINT uq_bd_idempotency UNIQUE (bd_khoa_chonglap);


--
-- Name: ho_so_doanh_nghiep uq_ho_so_doanh_nghiep_mst; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ho_so_doanh_nghiep
    ADD CONSTRAINT uq_ho_so_doanh_nghiep_mst UNIQUE (hsdn_masothue);


--
-- Name: ho_so_doanh_nghiep uq_ho_so_doanh_nghiep_nd; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ho_so_doanh_nghiep
    ADD CONSTRAINT uq_ho_so_doanh_nghiep_nd UNIQUE (nd_tendangnhap);


--
-- Name: gia_tham_chieu uq_reference_period_fuel; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gia_tham_chieu
    ADD CONSTRAINT uq_reference_period_fuel UNIQUE NULLS NOT DISTINCT (source, region, effective_date, effective_time, fuel_id);


--
-- Name: danh_gia uq_review_transaction; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.danh_gia
    ADD CONSTRAINT uq_review_transaction UNIQUE (gd_ma);


--
-- Name: tru_bom uq_tb_station; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tru_bom
    ADD CONSTRAINT uq_tb_station UNIQUE (tb_ma, tx_ma);


--
-- Name: tru_bom uq_tb_station_code; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tru_bom
    ADD CONSTRAINT uq_tb_station_code UNIQUE (tx_ma, tb_code);


--
-- Name: tru_bom_nhien_lieu uq_tbnl_scope; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tru_bom_nhien_lieu
    ADD CONSTRAINT uq_tbnl_scope UNIQUE (tb_ma, tx_ma, nl_ma);


--
-- Name: yeu_cau_duyet_doanh_nghiep uq_ycdn_lan_gui; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.yeu_cau_duyet_doanh_nghiep
    ADD CONSTRAINT uq_ycdn_lan_gui UNIQUE (hsdn_ma, ycdn_lan_gui);


--
-- Name: yeu_cau_duyet_tram uq_ycdt_lan_gui; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.yeu_cau_duyet_tram
    ADD CONSTRAINT uq_ycdt_lan_gui UNIQUE (tx_ma, ycdt_lan_gui);


--
-- Name: chi_tiet_giao_dich_pk; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX chi_tiet_giao_dich_pk ON public.chi_tiet_giao_dich USING btree (nl_ma, gd_ma);


--
-- Name: chitiet_yeucau_pk; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX chitiet_yeucau_pk ON public.chitiet_yeucau USING btree (yc_ma, nl_ma);


--
-- Name: ctgd_nl_fk; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ctgd_nl_fk ON public.chi_tiet_giao_dich USING btree (nl_ma);


--
-- Name: ctgt_gd_fk; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ctgt_gd_fk ON public.chi_tiet_giao_dich USING btree (gd_ma);


--
-- Name: danh_gia_pk; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX danh_gia_pk ON public.danh_gia USING btree (dg_ma);


--
-- Name: dg_tx_fk; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dg_tx_fk ON public.danh_gia USING btree (tx_ma);


--
-- Name: dich_vu_pk; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX dich_vu_pk ON public.dich_vu USING btree (dv_ma);


--
-- Name: dn_tx_fk; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dn_tx_fk ON public.tram_xang USING btree (nd_tendangnhap);


--
-- Name: doanh_nghiep_pk; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX doanh_nghiep_pk ON public.doanh_nghiep USING btree (nd_tendangnhap);


--
-- Name: don_vi_tinh_pk; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX don_vi_tinh_pk ON public.don_vi_tinh USING btree (dvt_ma);


--
-- Name: gb_nad_fk; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX gb_nad_fk ON public.gia USING btree (ngaygio);


--
-- Name: gb_nl_fk; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX gb_nl_fk ON public.gia USING btree (nl_ma);


--
-- Name: gb_tx_fk; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX gb_tx_fk ON public.gia USING btree (tx_ma);


--
-- Name: gd_td_fk; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX gd_td_fk ON public.giao_dich USING btree (ngaygio);


--
-- Name: gd_tklk_fk; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX gd_tklk_fk ON public.giao_dich USING btree (tklk_mathe);


--
-- Name: gd_tt_fk; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX gd_tt_fk ON public.giao_dich USING btree (tt_ma);


--
-- Name: gia_pk; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX gia_pk ON public.gia USING btree (ngaygio, tx_ma, nl_ma);


--
-- Name: giao_dich_pk; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX giao_dich_pk ON public.giao_dich USING btree (gd_ma);


--
-- Name: idx_bc_station_fuel; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bc_station_fuel ON public.bon_chua USING btree (tx_ma, nl_ma);


--
-- Name: idx_bd_pump; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bd_pump ON public.bien_dong_kho USING btree (tb_ma);


--
-- Name: idx_bd_reservation; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bd_reservation ON public.bien_dong_kho USING btree (yc_ma, nl_ma, bc_ma);


--
-- Name: idx_bd_station_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bd_station_date ON public.bien_dong_kho USING btree (tx_ma, bd_ngaytao);


--
-- Name: idx_bd_tank_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bd_tank_date ON public.bien_dong_kho USING btree (bc_ma, bd_ngaytao);


--
-- Name: idx_gc_active_tank; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_gc_active_tank ON public.giu_cho_nhien_lieu USING btree (bc_ma) WHERE ((gc_trangthai)::text = 'GIU_CHO'::text);


--
-- Name: idx_gc_station_state; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_gc_station_state ON public.giu_cho_nhien_lieu USING btree (tx_ma, gc_trangthai);


--
-- Name: idx_giao_dich_tx_ma; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_giao_dich_tx_ma ON public.giao_dich USING btree (tx_ma);


--
-- Name: idx_tbnl_station_fuel; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tbnl_station_fuel ON public.tru_bom_nhien_lieu USING btree (tx_ma, nl_ma);


--
-- Name: idx_tmc_ycdn; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tmc_ycdn ON public.tep_minh_chung USING btree (ycdn_ma);


--
-- Name: idx_tmc_ycdt; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tmc_ycdt ON public.tep_minh_chung USING btree (ycdt_ma);


--
-- Name: idx_tram_xang_congkhai; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tram_xang_congkhai ON public.tram_xang USING btree (nd_tendangnhap) WHERE (((tx_trangthai)::text = 'DA_DUYET'::text) AND (tx_congkhai = true));


--
-- Name: idx_yc_waiting_deadline; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_yc_waiting_deadline ON public.yeu_cau_do_xang USING btree (yc_het_han_luc, tx_ma, yc_ma) WHERE ((ttxn_ma = 'TTXN0001'::bpchar) AND (yc_het_han_luc IS NOT NULL));


--
-- Name: idx_ycdn_hsdn_ma; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ycdn_hsdn_ma ON public.yeu_cau_duyet_doanh_nghiep USING btree (hsdn_ma);


--
-- Name: idx_ycdn_qtv; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ycdn_qtv ON public.yeu_cau_duyet_doanh_nghiep USING btree (qtv_tendangnhap);


--
-- Name: idx_ycdn_trangthai_ngaygui; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ycdn_trangthai_ngaygui ON public.yeu_cau_duyet_doanh_nghiep USING btree (ycdn_trangthai, ycdn_ngaygui);


--
-- Name: idx_ycdt_qtv; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ycdt_qtv ON public.yeu_cau_duyet_tram USING btree (qtv_tendangnhap);


--
-- Name: idx_ycdt_trangthai_ngaygui; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ycdt_trangthai_ngaygui ON public.yeu_cau_duyet_tram USING btree (ycdt_trangthai, ycdt_ngaygui);


--
-- Name: idx_ycdt_tx_ma; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ycdt_tx_ma ON public.yeu_cau_duyet_tram USING btree (tx_ma);


--
-- Name: idx_yeu_cau_do_xang_pt_bienso; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_yeu_cau_do_xang_pt_bienso ON public.yeu_cau_do_xang USING btree (pt_bienso);


--
-- Name: kh_pt_fk; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX kh_pt_fk ON public.phuong_tien USING btree (nd_tendangnhap);


--
-- Name: kh_yc_fk; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX kh_yc_fk ON public.yeu_cau_do_xang USING btree (nd_tendangnhap);


--
-- Name: khach_hang_pk; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX khach_hang_pk ON public.khach_hang USING btree (nd_tendangnhap);


--
-- Name: loai_phuong_tien_pk; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX loai_phuong_tien_pk ON public.loai_phuong_tien USING btree (lpt_ma);


--
-- Name: nd_dg_fk; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX nd_dg_fk ON public.danh_gia USING btree (nd_tendangnhap);


--
-- Name: nd_gd_fk; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX nd_gd_fk ON public.giao_dich USING btree (nd_tendangnhap);


--
-- Name: ngan_hang_pk; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ngan_hang_pk ON public.ngan_hang USING btree (nh_ma);


--
-- Name: nguoi_dung_pk; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX nguoi_dung_pk ON public.nguoi_dung USING btree (nd_tendangnhap);


--
-- Name: nhien_lieu_pk; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX nhien_lieu_pk ON public.nhien_lieu USING btree (nl_ma);


--
-- Name: nl_dvt_fk; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX nl_dvt_fk ON public.nhien_lieu USING btree (dvt_ma);


--
-- Name: nl_yc_fk; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX nl_yc_fk ON public.chitiet_yeucau USING btree (nl_ma);


--
-- Name: phuong_tien_pk; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX phuong_tien_pk ON public.phuong_tien USING btree (pt_bienso);


--
-- Name: pt_lpt_fk; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX pt_lpt_fk ON public.phuong_tien USING btree (lpt_ma);


--
-- Name: tai_khoan_lien_ket_pk; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX tai_khoan_lien_ket_pk ON public.tai_khoan_lien_ket USING btree (tklk_mathe);


--
-- Name: td_dg_fk; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX td_dg_fk ON public.danh_gia USING btree (ngaygio);


--
-- Name: thoi_diem_pk; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX thoi_diem_pk ON public.thoi_diem USING btree (ngaygio);


--
-- Name: tklk_nh_fk; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX tklk_nh_fk ON public.tai_khoan_lien_ket USING btree (nh_ma);


--
-- Name: tram_xang_pk; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX tram_xang_pk ON public.tram_xang USING btree (tx_ma);


--
-- Name: trang_thai_pk; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX trang_thai_pk ON public.trang_thai USING btree (tt_ma);


--
-- Name: trang_thai_xac_nhan_pk; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX trang_thai_xac_nhan_pk ON public.trang_thai_xac_nhan USING btree (ttxn_ma);


--
-- Name: ttxn_ycdx_fk; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ttxn_ycdx_fk ON public.yeu_cau_do_xang USING btree (ttxn_ma);


--
-- Name: tx_dv2_fk; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX tx_dv2_fk ON public.tx_dv USING btree (tx_ma);


--
-- Name: tx_dv_fk; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX tx_dv_fk ON public.tx_dv USING btree (dv_ma);


--
-- Name: tx_dv_pk; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX tx_dv_pk ON public.tx_dv USING btree (dv_ma, tx_ma);


--
-- Name: tx_ycdx_fk; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX tx_ycdx_fk ON public.yeu_cau_do_xang USING btree (tx_ma);


--
-- Name: uq_bd_opening_tank; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_bd_opening_tank ON public.bien_dong_kho USING btree (bc_ma) WHERE ((bd_loai)::text = 'KHOI_TAO_DI_TRU'::text);


--
-- Name: uq_bd_sale_tank; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_bd_sale_tank ON public.bien_dong_kho USING btree (gd_ma, nl_ma, bc_ma) WHERE ((bd_loai)::text = 'XUAT'::text);


--
-- Name: uq_tb_one_request; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_tb_one_request ON public.tru_bom USING btree (yc_dang_bom) WHERE (yc_dang_bom IS NOT NULL);


--
-- Name: uq_ycdn_mot_cho_duyet; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_ycdn_mot_cho_duyet ON public.yeu_cau_duyet_doanh_nghiep USING btree (hsdn_ma) WHERE ((ycdn_trangthai)::text = 'CHO_DUYET'::text);


--
-- Name: uq_ycdt_mot_cho_duyet; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_ycdt_mot_cho_duyet ON public.yeu_cau_duyet_tram USING btree (tx_ma) WHERE ((ycdt_trangthai)::text = 'CHO_DUYET'::text);


--
-- Name: vi_tri_hien_tai_pk; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX vi_tri_hien_tai_pk ON public.vi_tri_hien_tai USING btree (nd_tendangnhap, thoigian);


--
-- Name: vt_nd_fk; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX vt_nd_fk ON public.vi_tri_hien_tai USING btree (nd_tendangnhap);


--
-- Name: yc_ct_fk; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX yc_ct_fk ON public.chitiet_yeucau USING btree (yc_ma);


--
-- Name: yeu_cau_do_xang_pk; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX yeu_cau_do_xang_pk ON public.yeu_cau_do_xang USING btree (yc_ma);


--
-- Name: bon_chua trg_bc_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_bc_immutable BEFORE DELETE OR UPDATE ON public.bon_chua FOR EACH ROW EXECUTE FUNCTION public.phase57_immutable_guard();


--
-- Name: bien_dong_kho trg_bd_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_bd_immutable BEFORE DELETE OR UPDATE ON public.bien_dong_kho FOR EACH ROW EXECUTE FUNCTION public.phase57_immutable_guard();


--
-- Name: bien_dong_kho trg_bd_scope; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_bd_scope BEFORE INSERT ON public.bien_dong_kho FOR EACH ROW EXECUTE FUNCTION public.phase57_scope_guard();


--
-- Name: giu_cho_nhien_lieu trg_gc_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_gc_immutable BEFORE DELETE OR UPDATE ON public.giu_cho_nhien_lieu FOR EACH ROW EXECUTE FUNCTION public.phase57_immutable_guard();


--
-- Name: giu_cho_nhien_lieu trg_gc_scope; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_gc_scope BEFORE INSERT OR UPDATE ON public.giu_cho_nhien_lieu FOR EACH ROW EXECUTE FUNCTION public.phase57_scope_guard();


--
-- Name: tru_bom trg_tb_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_tb_immutable BEFORE DELETE OR UPDATE ON public.tru_bom FOR EACH ROW EXECUTE FUNCTION public.phase57_immutable_guard();


--
-- Name: tru_bom trg_tb_scope; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_tb_scope BEFORE INSERT OR UPDATE ON public.tru_bom FOR EACH ROW EXECUTE FUNCTION public.phase57_scope_guard();


--
-- Name: bien_dong_kho bien_dong_kho_nd_tendangnhap_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bien_dong_kho
    ADD CONSTRAINT bien_dong_kho_nd_tendangnhap_fkey FOREIGN KEY (nd_tendangnhap) REFERENCES public.nguoi_dung(nd_tendangnhap) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: bon_chua bon_chua_nl_ma_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bon_chua
    ADD CONSTRAINT bon_chua_nl_ma_fkey FOREIGN KEY (nl_ma) REFERENCES public.nhien_lieu(nl_ma) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: bon_chua bon_chua_tx_ma_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bon_chua
    ADD CONSTRAINT bon_chua_tx_ma_fkey FOREIGN KEY (tx_ma) REFERENCES public.tram_xang(tx_ma) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: bien_dong_kho fk_bd_pump_fuel_scope; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bien_dong_kho
    ADD CONSTRAINT fk_bd_pump_fuel_scope FOREIGN KEY (tb_ma, tx_ma, nl_ma) REFERENCES public.tru_bom_nhien_lieu(tb_ma, tx_ma, nl_ma) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: bien_dong_kho fk_bd_reservation; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bien_dong_kho
    ADD CONSTRAINT fk_bd_reservation FOREIGN KEY (yc_ma, nl_ma, bc_ma) REFERENCES public.giu_cho_nhien_lieu(yc_ma, nl_ma, bc_ma) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: bien_dong_kho fk_bd_sale_item; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bien_dong_kho
    ADD CONSTRAINT fk_bd_sale_item FOREIGN KEY (nl_ma, gd_ma) REFERENCES public.chi_tiet_giao_dich(nl_ma, gd_ma) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: bien_dong_kho fk_bd_tank_scope; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bien_dong_kho
    ADD CONSTRAINT fk_bd_tank_scope FOREIGN KEY (bc_ma, tx_ma, nl_ma) REFERENCES public.bon_chua(bc_ma, tx_ma, nl_ma) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: chi_tiet_giao_dich fk_chi_tiet_ctgd_nl_nhien_li; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chi_tiet_giao_dich
    ADD CONSTRAINT fk_chi_tiet_ctgd_nl_nhien_li FOREIGN KEY (nl_ma) REFERENCES public.nhien_lieu(nl_ma) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: chi_tiet_giao_dich fk_chi_tiet_ctgt_gd_giao_dic; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chi_tiet_giao_dich
    ADD CONSTRAINT fk_chi_tiet_ctgt_gd_giao_dic FOREIGN KEY (gd_ma) REFERENCES public.giao_dich(gd_ma) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: chitiet_yeucau fk_chitiet__nl_yc_nhien_li; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chitiet_yeucau
    ADD CONSTRAINT fk_chitiet__nl_yc_nhien_li FOREIGN KEY (nl_ma) REFERENCES public.nhien_lieu(nl_ma) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: chitiet_yeucau fk_chitiet__yc_ct_yeu_cau_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chitiet_yeucau
    ADD CONSTRAINT fk_chitiet__yc_ct_yeu_cau_ FOREIGN KEY (yc_ma) REFERENCES public.yeu_cau_do_xang(yc_ma) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: danh_gia fk_danh_gia_dg_tx_tram_xan; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.danh_gia
    ADD CONSTRAINT fk_danh_gia_dg_tx_tram_xan FOREIGN KEY (tx_ma) REFERENCES public.tram_xang(tx_ma) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: danh_gia fk_danh_gia_nd_dg_nguoi_du; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.danh_gia
    ADD CONSTRAINT fk_danh_gia_nd_dg_nguoi_du FOREIGN KEY (nd_tendangnhap) REFERENCES public.nguoi_dung(nd_tendangnhap) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: danh_gia fk_danh_gia_td_dg_thoi_die; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.danh_gia
    ADD CONSTRAINT fk_danh_gia_td_dg_thoi_die FOREIGN KEY (ngaygio) REFERENCES public.thoi_diem(ngaygio) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: doanh_nghiep fk_doanh_ng_nguoidung_nguoi_du; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.doanh_nghiep
    ADD CONSTRAINT fk_doanh_ng_nguoidung_nguoi_du FOREIGN KEY (nd_tendangnhap) REFERENCES public.nguoi_dung(nd_tendangnhap) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: giu_cho_nhien_lieu fk_gc_price_period; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.giu_cho_nhien_lieu
    ADD CONSTRAINT fk_gc_price_period FOREIGN KEY (gia_ngaygio, tx_ma, nl_ma) REFERENCES public.gia(ngaygio, tx_ma, nl_ma) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: giu_cho_nhien_lieu fk_gc_request_item; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.giu_cho_nhien_lieu
    ADD CONSTRAINT fk_gc_request_item FOREIGN KEY (yc_ma, nl_ma) REFERENCES public.chitiet_yeucau(yc_ma, nl_ma) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: giu_cho_nhien_lieu fk_gc_tank_scope; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.giu_cho_nhien_lieu
    ADD CONSTRAINT fk_gc_tank_scope FOREIGN KEY (bc_ma, tx_ma, nl_ma) REFERENCES public.bon_chua(bc_ma, tx_ma, nl_ma) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: gia fk_gia_gb_nad_thoi_die; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gia
    ADD CONSTRAINT fk_gia_gb_nad_thoi_die FOREIGN KEY (ngaygio) REFERENCES public.thoi_diem(ngaygio) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: gia fk_gia_gb_nl_nhien_li; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gia
    ADD CONSTRAINT fk_gia_gb_nl_nhien_li FOREIGN KEY (nl_ma) REFERENCES public.nhien_lieu(nl_ma) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: gia fk_gia_gb_tx_tram_xan; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gia
    ADD CONSTRAINT fk_gia_gb_tx_tram_xan FOREIGN KEY (tx_ma) REFERENCES public.tram_xang(tx_ma) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: giao_dich fk_giao_dic_gd_td_thoi_die; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.giao_dich
    ADD CONSTRAINT fk_giao_dic_gd_td_thoi_die FOREIGN KEY (ngaygio) REFERENCES public.thoi_diem(ngaygio) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: giao_dich fk_giao_dic_gd_tklk_tai_khoa; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.giao_dich
    ADD CONSTRAINT fk_giao_dic_gd_tklk_tai_khoa FOREIGN KEY (tklk_mathe) REFERENCES public.tai_khoan_lien_ket(tklk_mathe) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: giao_dich fk_giao_dic_gd_tt_trang_th; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.giao_dich
    ADD CONSTRAINT fk_giao_dic_gd_tt_trang_th FOREIGN KEY (tt_ma) REFERENCES public.trang_thai(tt_ma) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: giao_dich fk_giao_dic_gd_ycdx_yeu_cau_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.giao_dich
    ADD CONSTRAINT fk_giao_dic_gd_ycdx_yeu_cau_ FOREIGN KEY (yc_ma) REFERENCES public.yeu_cau_do_xang(yc_ma) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: giao_dich fk_giao_dic_nd_gd_nguoi_du; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.giao_dich
    ADD CONSTRAINT fk_giao_dic_nd_gd_nguoi_du FOREIGN KEY (nd_tendangnhap) REFERENCES public.nguoi_dung(nd_tendangnhap) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: giao_dich fk_giao_dich_tram_xang; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.giao_dich
    ADD CONSTRAINT fk_giao_dich_tram_xang FOREIGN KEY (tx_ma) REFERENCES public.tram_xang(tx_ma) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: ho_so_doanh_nghiep fk_ho_so_doanh_nghiep_doanh_nghiep; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ho_so_doanh_nghiep
    ADD CONSTRAINT fk_ho_so_doanh_nghiep_doanh_nghiep FOREIGN KEY (nd_tendangnhap) REFERENCES public.doanh_nghiep(nd_tendangnhap) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: khach_hang fk_khach_ha_nguoidung_nguoi_du; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.khach_hang
    ADD CONSTRAINT fk_khach_ha_nguoidung_nguoi_du FOREIGN KEY (nd_tendangnhap) REFERENCES public.nguoi_dung(nd_tendangnhap) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: nhien_lieu fk_nhien_li_nl_dvt_don_vi_t; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.nhien_lieu
    ADD CONSTRAINT fk_nhien_li_nl_dvt_don_vi_t FOREIGN KEY (dvt_ma) REFERENCES public.don_vi_tinh(dvt_ma) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: phuong_tien fk_phuong_t_kh_pt_khach_ha; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.phuong_tien
    ADD CONSTRAINT fk_phuong_t_kh_pt_khach_ha FOREIGN KEY (nd_tendangnhap) REFERENCES public.khach_hang(nd_tendangnhap) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: phuong_tien fk_phuong_t_pt_lpt_loai_phu; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.phuong_tien
    ADD CONSTRAINT fk_phuong_t_pt_lpt_loai_phu FOREIGN KEY (lpt_ma) REFERENCES public.loai_phuong_tien(lpt_ma) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: quan_tri_vien fk_quan_tri_vien_nguoi_dung; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quan_tri_vien
    ADD CONSTRAINT fk_quan_tri_vien_nguoi_dung FOREIGN KEY (nd_tendangnhap) REFERENCES public.nguoi_dung(nd_tendangnhap) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: danh_gia fk_review_transaction; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.danh_gia
    ADD CONSTRAINT fk_review_transaction FOREIGN KEY (gd_ma) REFERENCES public.giao_dich(gd_ma) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: tai_khoan_lien_ket fk_tai_khoa_nd_tklk2_nguoi_du; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tai_khoan_lien_ket
    ADD CONSTRAINT fk_tai_khoa_nd_tklk2_nguoi_du FOREIGN KEY (nd_tendangnhap) REFERENCES public.nguoi_dung(nd_tendangnhap) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: tai_khoan_lien_ket fk_tai_khoa_tklk_nh_ngan_han; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tai_khoan_lien_ket
    ADD CONSTRAINT fk_tai_khoa_tklk_nh_ngan_han FOREIGN KEY (nh_ma) REFERENCES public.ngan_hang(nh_ma) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: tru_bom_nhien_lieu fk_tbnl_pump_scope; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tru_bom_nhien_lieu
    ADD CONSTRAINT fk_tbnl_pump_scope FOREIGN KEY (tb_ma, tx_ma) REFERENCES public.tru_bom(tb_ma, tx_ma) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: tep_minh_chung fk_tmc_ycdn; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tep_minh_chung
    ADD CONSTRAINT fk_tmc_ycdn FOREIGN KEY (ycdn_ma) REFERENCES public.yeu_cau_duyet_doanh_nghiep(ycdn_ma) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: tep_minh_chung fk_tmc_ycdt; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tep_minh_chung
    ADD CONSTRAINT fk_tmc_ycdt FOREIGN KEY (ycdt_ma) REFERENCES public.yeu_cau_duyet_tram(ycdt_ma) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: tram_xang fk_tram_xan_dn_tx_doanh_ng; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tram_xang
    ADD CONSTRAINT fk_tram_xan_dn_tx_doanh_ng FOREIGN KEY (nd_tendangnhap) REFERENCES public.doanh_nghiep(nd_tendangnhap) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: tx_dv fk_tx_dv_tx_dv2_tram_xan; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tx_dv
    ADD CONSTRAINT fk_tx_dv_tx_dv2_tram_xan FOREIGN KEY (tx_ma) REFERENCES public.tram_xang(tx_ma) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: tx_dv fk_tx_dv_tx_dv_dich_vu; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tx_dv
    ADD CONSTRAINT fk_tx_dv_tx_dv_dich_vu FOREIGN KEY (dv_ma) REFERENCES public.dich_vu(dv_ma) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: vi_tri_hien_tai fk_vi_tri_h_vt_nd_nguoi_du; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vi_tri_hien_tai
    ADD CONSTRAINT fk_vi_tri_h_vt_nd_nguoi_du FOREIGN KEY (nd_tendangnhap) REFERENCES public.nguoi_dung(nd_tendangnhap) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: yeu_cau_do_xang fk_yc_closed_actor; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.yeu_cau_do_xang
    ADD CONSTRAINT fk_yc_closed_actor FOREIGN KEY (yc_dong_boi) REFERENCES public.nguoi_dung(nd_tendangnhap) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: yeu_cau_duyet_doanh_nghiep fk_ycdn_ho_so_doanh_nghiep; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.yeu_cau_duyet_doanh_nghiep
    ADD CONSTRAINT fk_ycdn_ho_so_doanh_nghiep FOREIGN KEY (hsdn_ma) REFERENCES public.ho_so_doanh_nghiep(hsdn_ma) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: yeu_cau_duyet_doanh_nghiep fk_ycdn_quan_tri_vien; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.yeu_cau_duyet_doanh_nghiep
    ADD CONSTRAINT fk_ycdn_quan_tri_vien FOREIGN KEY (qtv_tendangnhap) REFERENCES public.quan_tri_vien(nd_tendangnhap) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: yeu_cau_duyet_tram fk_ycdt_quan_tri_vien; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.yeu_cau_duyet_tram
    ADD CONSTRAINT fk_ycdt_quan_tri_vien FOREIGN KEY (qtv_tendangnhap) REFERENCES public.quan_tri_vien(nd_tendangnhap) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: yeu_cau_duyet_tram fk_ycdt_tram_xang; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.yeu_cau_duyet_tram
    ADD CONSTRAINT fk_ycdt_tram_xang FOREIGN KEY (tx_ma) REFERENCES public.tram_xang(tx_ma) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: yeu_cau_do_xang fk_yeu_cau__kh_yc_khach_ha; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.yeu_cau_do_xang
    ADD CONSTRAINT fk_yeu_cau__kh_yc_khach_ha FOREIGN KEY (nd_tendangnhap) REFERENCES public.khach_hang(nd_tendangnhap) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: yeu_cau_do_xang fk_yeu_cau__ttxn_ycdx_trang_th; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.yeu_cau_do_xang
    ADD CONSTRAINT fk_yeu_cau__ttxn_ycdx_trang_th FOREIGN KEY (ttxn_ma) REFERENCES public.trang_thai_xac_nhan(ttxn_ma) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: yeu_cau_do_xang fk_yeu_cau__tx_ycdx_tram_xan; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.yeu_cau_do_xang
    ADD CONSTRAINT fk_yeu_cau__tx_ycdx_tram_xan FOREIGN KEY (tx_ma) REFERENCES public.tram_xang(tx_ma) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: yeu_cau_do_xang fk_yeu_cau_do_xang_phuong_tien; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.yeu_cau_do_xang
    ADD CONSTRAINT fk_yeu_cau_do_xang_phuong_tien FOREIGN KEY (pt_bienso) REFERENCES public.phuong_tien(pt_bienso) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: gia_tham_chieu gia_tham_chieu_fuel_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gia_tham_chieu
    ADD CONSTRAINT gia_tham_chieu_fuel_id_fkey FOREIGN KEY (fuel_id) REFERENCES public.nhien_lieu(nl_ma) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: giu_cho_nhien_lieu giu_cho_nhien_lieu_nd_tendangnhap_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.giu_cho_nhien_lieu
    ADD CONSTRAINT giu_cho_nhien_lieu_nd_tendangnhap_fkey FOREIGN KEY (nd_tendangnhap) REFERENCES public.nguoi_dung(nd_tendangnhap) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: he_so_giao_thong he_so_giao_thong_td_ma_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.he_so_giao_thong
    ADD CONSTRAINT he_so_giao_thong_td_ma_fkey FOREIGN KEY (td_ma) REFERENCES public.tuyen_duong(td_ma);


--
-- Name: tru_bom_nhien_lieu tru_bom_nhien_lieu_nl_ma_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tru_bom_nhien_lieu
    ADD CONSTRAINT tru_bom_nhien_lieu_nl_ma_fkey FOREIGN KEY (nl_ma) REFERENCES public.nhien_lieu(nl_ma) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: tru_bom tru_bom_tx_ma_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tru_bom
    ADD CONSTRAINT tru_bom_tx_ma_fkey FOREIGN KEY (tx_ma) REFERENCES public.tram_xang(tx_ma) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: tru_bom tru_bom_yc_dang_bom_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tru_bom
    ADD CONSTRAINT tru_bom_yc_dang_bom_fkey FOREIGN KEY (yc_dang_bom) REFERENCES public.yeu_cau_do_xang(yc_ma) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- PostgreSQL database dump complete
--


COMMIT;
