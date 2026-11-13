-- OPTIONAL MANUAL starter import into an EMPTY database with approved 35-table schema.
-- Never invoked by init-dev. No migrations, reset, DELETE, UPDATE or credentials.
-- Refuses any pre-existing public row, even in lookup tables. Use a fresh test DB.
BEGIN;
DO $$ DECLARE r record; occupied boolean; BEGIN
  IF current_database() <> 'DB_TRAMXANG' OR
     (SELECT count(*) FROM pg_tables WHERE schemaname='public') <> 35 OR
     EXISTS (SELECT 1 FROM pg_namespace WHERE nspname NOT IN ('public','information_schema') AND left(nspname,3)<>'pg_') THEN
    RAISE EXCEPTION 'Expected empty DB_TRAMXANG with reviewed 35-table schema';
  END IF;
  FOR r IN SELECT tablename FROM pg_tables WHERE schemaname='public' LOOP
    EXECUTE format('SELECT EXISTS (SELECT 1 FROM public.%I)',r.tablename) INTO occupied;
    IF occupied THEN RAISE EXCEPTION 'Starter import refuses existing data: %',r.tablename; END IF;
  END LOOP;
END $$;
INSERT INTO public.trang_thai (tt_ma,tt_ten) VALUES ('TT000001','Thành công');
INSERT INTO public.trang_thai (tt_ma,tt_ten) VALUES ('TT000002','Thất bại');
INSERT INTO public.trang_thai (tt_ma,tt_ten) VALUES ('TT000003','Đang xử lý');
INSERT INTO public.trang_thai_xac_nhan (ttxn_ma,ttxn_ten) VALUES ('TTXN0001','Chờ duyệt');
INSERT INTO public.trang_thai_xac_nhan (ttxn_ma,ttxn_ten) VALUES ('TTXN0002','Đã xác nhận');
INSERT INTO public.trang_thai_xac_nhan (ttxn_ma,ttxn_ten) VALUES ('TTXN0003','Đang bơm');
INSERT INTO public.trang_thai_xac_nhan (ttxn_ma,ttxn_ten) VALUES ('TTXN0004','Hoàn thành');
INSERT INTO public.trang_thai_xac_nhan (ttxn_ma,ttxn_ten) VALUES ('TTXN0005','Từ chối');
INSERT INTO public.trang_thai_xac_nhan (ttxn_ma,ttxn_ten) VALUES ('TTXN0006','Đã hủy');
INSERT INTO public.trang_thai_xac_nhan (ttxn_ma,ttxn_ten) VALUES ('TTXN0007','Hết hạn');
INSERT INTO public.don_vi_tinh (dvt_ma,dvt_ten) VALUES ('DVT00001','Lít');
INSERT INTO public.loai_phuong_tien (lpt_ma,lpt_ten) VALUES ('LPT00001','Xe máy');
INSERT INTO public.loai_phuong_tien (lpt_ma,lpt_ten) VALUES ('LPT00002','Ô tô');
INSERT INTO public.nhien_lieu (nl_ma,dvt_ma,nl_ten) VALUES ('NL000001','DVT00001','Xăng E10 RON 95-III');
INSERT INTO public.nhien_lieu (nl_ma,dvt_ma,nl_ten) VALUES ('NL000002','DVT00001','E5 RON 92-II');
INSERT INTO public.nhien_lieu (nl_ma,dvt_ma,nl_ten) VALUES ('NL000003','DVT00001','Diesel DO 0,05S-II');
COMMIT;
